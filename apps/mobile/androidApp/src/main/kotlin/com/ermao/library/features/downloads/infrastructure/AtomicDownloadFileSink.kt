package com.ermao.library.features.downloads.infrastructure

import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadByteSink
import com.ermao.library.shared.modules.downloads.DownloadByteSinkSession
import com.ermao.library.shared.modules.downloads.DownloadBundleByteSink
import com.ermao.library.shared.modules.downloads.DownloadBundleByteSinkSession
import com.ermao.library.shared.modules.downloads.DownloadBundleMemberSinkRequest
import com.ermao.library.shared.modules.downloads.DownloadBundleSinkRequest
import com.ermao.library.shared.modules.downloads.DownloadSinkRequest
import java.io.File
import java.io.FileOutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

class AtomicDownloadFileSink(private val rootDirectory: File) : DownloadByteSink, DownloadBundleByteSink {
    override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession {
        return begin(
            namespace = AndroidDownloadNamespace(
                request.namespace.serverIdentity,
                request.namespace.userId,
                request.namespace.authorizationVersion,
            ),
            resourceId = request.resourceId,
            assetId = request.assetId,
            resumeFromBytes = request.resumeFromBytes,
        )
    }

    override suspend fun beginBundle(request: DownloadBundleSinkRequest): DownloadBundleByteSinkSession =
        withContext(Dispatchers.IO) {
            val namespaceKey = sha256(
                "${request.namespace.serverIdentity}|${request.namespace.userId}|${request.namespace.authorizationVersion}",
            )
            val artifactKey = sha256("${request.resourceId}:${request.artifactId}")
            val taskKey = sha256(request.taskId).take(16)
            val relativeDirectory = "$namespaceKey/artifacts"
            val directory = File(rootDirectory, relativeDirectory).apply { mkdirs() }
            val staging = File(directory, ".$artifactKey-$taskKey.bundle.part")
            val final = File(directory, "$artifactKey-$taskKey.bundle")
            staging.deleteRecursively()
            final.deleteRecursively()
            require(staging.mkdirs()) { "Unable to create bundle staging directory" }
            BundleSession(
                request = request,
                stagingDirectory = staging,
                finalDirectory = final,
                localReference = "$relativeDirectory/${final.name}",
            )
        }

    suspend fun begin(
        namespace: AndroidDownloadNamespace,
        resourceId: String,
        assetId: String,
        resumeFromBytes: Long = 0,
    ): Session = withContext(Dispatchers.IO) {
        require(resourceId.isNotBlank())
        require(assetId.isNotBlank())
        val namespaceKey = sha256("${namespace.serverIdentity}|${namespace.userId}|${namespace.authorizationVersion}")
        val artifactKey = sha256("$resourceId:$assetId")
        val relativeDirectory = "$namespaceKey/artifacts"
        val directory = File(rootDirectory, relativeDirectory).apply { mkdirs() }
        val part = File(directory, "$artifactKey.part")
        val final = File(directory, "$artifactKey.bin")
        if (resumeFromBytes == 0L) part.delete()
        require((if (part.exists()) part.length() else 0L) == resumeFromBytes) {
            "Partial download does not match the requested range"
        }
        Session(
            part,
            final,
            "$relativeDirectory/$artifactKey.bin",
            FileOutputStream(part, resumeFromBytes > 0),
            resumeFromBytes,
        )
    }

    fun resolveLocalReference(localReference: String): File? {
        if (localReference.isBlank() || localReference.startsWith('/') || localReference.contains('\\')) return null
        val root = rootDirectory.canonicalFile
        val candidate = File(root, localReference).canonicalFile
        val rootPrefix = root.path + File.separator
        return candidate.takeIf { it.path.startsWith(rootPrefix) }
    }

    fun hasLocalArtifact(localReference: String?): Boolean {
        if (localReference.isNullOrBlank()) return false
        val file = resolveLocalReference(localReference) ?: return false
        return (file.isFile && file.length() > 0L) ||
            (file.isDirectory && File(file, BUNDLE_MANIFEST_NAME).isFile)
    }

    suspend fun replaceLocalArtifact(localReference: String, parsedSource: File) = withContext(Dispatchers.IO) {
        val target = requireNotNull(resolveLocalReference(localReference)) { "Download reference is invalid" }
        require(parsedSource.isFile && parsedSource.length() > 0L) { "Parsed Reader source is missing" }
        target.parentFile?.mkdirs()
        val temporary = File(target.parentFile, ".${target.name}.${System.nanoTime()}.repair")
        try {
            parsedSource.inputStream().use { input ->
                FileOutputStream(temporary).use { output ->
                    input.copyTo(output)
                    output.fd.sync()
                }
            }
            require(temporary.length() == parsedSource.length()) { "Reader repair copy is incomplete" }
            atomicReplace(temporary, target)
        } finally {
            temporary.delete()
        }
    }

    class Session internal constructor(
        private val partFile: File,
        private val finalFile: File,
        private val localReference: String,
        private var output: FileOutputStream?,
        resumeFromBytes: Long = 0,
    ) : DownloadByteSinkSession {
        private var writtenBytes = resumeFromBytes

        override suspend fun write(bytes: ByteArray) = withContext(Dispatchers.IO) {
            check(output != null) { "Download sink session is closed" }
            if (bytes.isNotEmpty()) {
                output?.write(bytes)
                writtenBytes += bytes.size
            }
        }

        override suspend fun commit(expectedTotalBytes: Long): String = withContext(Dispatchers.IO) {
            require(expectedTotalBytes >= 0)
            val active = checkNotNull(output) { "Download sink session is closed" }
            if (expectedTotalBytes != writtenBytes) {
                abortInternal()
                throw AndroidDownloadStorageException("Downloaded byte count does not match the manifest")
            }
            active.fd.sync()
            active.close()
            output = null
            atomicReplace(partFile, finalFile)
            localReference
        }

        override suspend fun abort() = withContext(Dispatchers.IO) { abortInternal() }

        override suspend fun pause() = withContext(Dispatchers.IO) {
            output?.fd?.sync()
            output?.close()
            output = null
        }

        private fun abortInternal() {
            runCatching { output?.close() }
            output = null
            partFile.delete()
        }
    }

    private class BundleSession(
        private val request: DownloadBundleSinkRequest,
        private val stagingDirectory: File,
        private val finalDirectory: File,
        private val localReference: String,
    ) : DownloadBundleByteSinkSession {
        private val committedMembers = linkedMapOf<Int, BundleManifestMember>()
        private var closed = false

        override suspend fun beginMember(
            request: DownloadBundleMemberSinkRequest,
        ): DownloadByteSinkSession = withContext(Dispatchers.IO) {
            check(!closed) { "Download bundle is closed" }
            require(request.sequenceIndex in 0 until this@BundleSession.request.memberCount)
            require(request.sequenceIndex !in committedMembers) { "Download bundle member is duplicated" }
            val extension = extensionForMimeType(request.mimeType)
            val stableName = request.sequenceIndex.toString().padStart(6, '0') + "-" +
                sha256(request.assetId).take(16) + ".$extension"
            val part = File(stagingDirectory, ".$stableName.part")
            val final = File(stagingDirectory, stableName)
            part.delete()
            final.delete()
            BundleMemberSession(
                delegate = Session(
                    partFile = part,
                    finalFile = final,
                    localReference = stableName,
                    output = FileOutputStream(part),
                ),
                onCommitted = {
                    committedMembers[request.sequenceIndex] = BundleManifestMember(
                        assetId = request.assetId,
                        sequenceIndex = request.sequenceIndex,
                        mimeType = request.mimeType,
                        sizeBytes = request.expectedBytes,
                        fileName = stableName,
                    )
                },
            )
        }

        override suspend fun commit(): String = withContext(Dispatchers.IO) {
            check(!closed) { "Download bundle is closed" }
            require(committedMembers.keys.toList() == (0 until request.memberCount).toList()) {
                "Download bundle is incomplete"
            }
            val members = committedMembers.values.toList()
            require(members.sumOf(BundleManifestMember::sizeBytes) == request.expectedTotalBytes) {
                "Download bundle byte count does not match the manifest"
            }
            members.forEach { member ->
                val file = File(stagingDirectory, member.fileName)
                require(file.isFile && file.length() == member.sizeBytes) { "Download bundle member is invalid" }
                require(detectImageMime(file) == member.mimeType) { "Download bundle member MIME is invalid" }
            }
            val manifest = BundleManifest(
                contractVersion = DOWNLOAD_BUNDLE_CONTRACT_VERSION,
                artifactKind = request.artifactKind.name,
                resourceId = request.resourceId,
                artifactId = request.artifactId,
                totalBytes = request.expectedTotalBytes,
                members = members,
            )
            FileOutputStream(File(stagingDirectory, BUNDLE_MANIFEST_NAME)).use { output ->
                output.write(BUNDLE_JSON.encodeToString(manifest).encodeToByteArray())
                output.fd.sync()
            }
            atomicReplace(stagingDirectory, finalDirectory)
            closed = true
            localReference
        }

        override suspend fun abort() = withContext(Dispatchers.IO) {
            if (!closed) stagingDirectory.deleteRecursively()
            closed = true
        }
    }

    private class BundleMemberSession(
        private val delegate: Session,
        private val onCommitted: () -> Unit,
    ) : DownloadByteSinkSession {
        private var committed = false

        override suspend fun write(bytes: ByteArray) = delegate.write(bytes)

        override suspend fun commit(expectedTotalBytes: Long): String {
            val reference = delegate.commit(expectedTotalBytes)
            check(!committed)
            committed = true
            onCommitted()
            return reference
        }

        override suspend fun abort() = delegate.abort()
        override suspend fun pause() = delegate.abort()
    }

    @Serializable
    private data class BundleManifest(
        val contractVersion: Int,
        val artifactKind: String,
        val resourceId: String,
        val artifactId: String,
        val totalBytes: Long,
        val members: List<BundleManifestMember>,
    )

    @Serializable
    private data class BundleManifestMember(
        val assetId: String,
        val sequenceIndex: Int,
        val mimeType: String,
        val sizeBytes: Long,
        val fileName: String,
    )

    private companion object {
        const val DOWNLOAD_BUNDLE_CONTRACT_VERSION = 4
        const val BUNDLE_MANIFEST_NAME = "bundle.json"
        val BUNDLE_JSON = Json { encodeDefaults = true }

        fun extensionForMimeType(mimeType: String): String = when (mimeType.lowercase()) {
            "image/jpeg" -> "jpg"
            "image/png" -> "png"
            "image/gif" -> "gif"
            "image/webp" -> "webp"
            else -> throw IllegalArgumentException("Unsupported bundle member MIME type")
        }

        fun detectImageMime(file: File): String? {
            val bytes = ByteArray(16)
            val count = file.inputStream().buffered().use { it.read(bytes) }
            val header = bytes.copyOf(count.coerceAtLeast(0))
            return when {
                header.size >= 3 && header[0] == 0xFF.toByte() && header[1] == 0xD8.toByte() && header[2] == 0xFF.toByte() -> "image/jpeg"
                header.size >= 8 && header.copyOfRange(0, 8).contentEquals(
                    byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A),
                ) -> "image/png"
                header.size >= 6 && header.copyOfRange(0, 6).decodeToString() in setOf("GIF87a", "GIF89a") -> "image/gif"
                header.size >= 12 && header.copyOfRange(0, 4).decodeToString() == "RIFF" &&
                    header.copyOfRange(8, 12).decodeToString() == "WEBP" -> "image/webp"
                else -> null
            }
        }
    }
}
