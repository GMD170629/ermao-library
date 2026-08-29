package com.ermao.library.features.downloads.infrastructure

import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadByteSink
import com.ermao.library.shared.modules.downloads.DownloadStoredBytes
import com.ermao.library.shared.modules.downloads.DownloadArtifactKind
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
    override suspend fun inspect(request: DownloadSinkRequest): DownloadStoredBytes = withContext(Dispatchers.IO) {
        val artifactKey = taskArtifactKey(request.resourceId, request.assetId, request.taskId)
        val relativeDirectory = relativeArtifactDirectory(
            request.namespace.serverIdentity,
            request.namespace.userId,
            request.namespace.authorizationVersion,
        )
        val isBundle = request.artifactKind == DownloadArtifactKind.OriginalPageSet
        val finalName = artifactKey + if (isBundle) ".bundle" else ".bin"
        if (hasLocalArtifact("$relativeDirectory/$finalName", request.expectedTotalBytes)) {
            return@withContext DownloadStoredBytes(0, "$relativeDirectory/$finalName")
        }
        val part = File(rootDirectory, "$relativeDirectory/$artifactKey.part")
        val size = if (part.isFile && !isBundle) part.length() else 0
        DownloadStoredBytes(if (size < request.expectedTotalBytes) size else 0)
    }

    override suspend fun discard(request: DownloadSinkRequest) = withContext(Dispatchers.IO) {
        val artifactKey = taskArtifactKey(request.resourceId, request.assetId, request.taskId)
        val directory = File(
            rootDirectory,
            relativeArtifactDirectory(
                request.namespace.serverIdentity,
                request.namespace.userId,
                request.namespace.authorizationVersion,
            ),
        )
        listOf(
            File(directory, "$artifactKey.part"),
            File(directory, "$artifactKey.bin"),
            File(directory, "$artifactKey.bundle"),
            File(directory, ".$artifactKey.bundle.part"),
        ).forEach { candidate ->
            if (candidate.exists() && !candidate.deleteRecursively()) {
                throw AndroidDownloadStorageException("Unable to discard rebuilt download bytes")
            }
        }
    }

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
            taskId = request.taskId,
        )
    }

    override suspend fun beginBundle(request: DownloadBundleSinkRequest): DownloadBundleByteSinkSession =
        withContext(Dispatchers.IO) {
            val artifactKey = taskArtifactKey(request.resourceId, request.artifactId, request.taskId)
            val relativeDirectory = relativeArtifactDirectory(
                request.namespace.serverIdentity,
                request.namespace.userId,
                request.namespace.authorizationVersion,
            )
            val directory = File(rootDirectory, relativeDirectory).apply { mkdirs() }
            val staging = File(directory, ".$artifactKey.bundle.part")
            val final = File(directory, "$artifactKey.bundle")
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
        taskId: String,
    ): Session = withContext(Dispatchers.IO) {
        require(resourceId.isNotBlank())
        require(assetId.isNotBlank())
        val artifactKey = taskArtifactKey(resourceId, assetId, taskId)
        val relativeDirectory = relativeArtifactDirectory(
            namespace.serverIdentity,
            namespace.userId,
            namespace.authorizationVersion,
        )
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

    fun hasLocalArtifact(localReference: String?, expectedBytes: Long? = null): Boolean {
        if (localReference.isNullOrBlank()) return false
        val file = resolveLocalReference(localReference) ?: return false
        if (file.isFile) return file.length() > 0L && (expectedBytes == null || file.length() == expectedBytes)
        if (!file.isDirectory) return false
        val manifestFile = File(file, BUNDLE_MANIFEST_NAME)
        if (!manifestFile.isFile || manifestFile.length() > 8 * 1024 * 1024) return false
        val manifest = try { BUNDLE_JSON.decodeFromString<BundleManifest>(manifestFile.readText()) }
        catch (_: kotlinx.serialization.SerializationException) { return false }
        if (manifest.contractVersion != DOWNLOAD_BUNDLE_CONTRACT_VERSION ||
            manifest.artifactKind != DownloadArtifactKind.OriginalPageSet.name || manifest.members.isEmpty() ||
            (expectedBytes != null && manifest.totalBytes != expectedBytes) ||
            manifest.members.map { it.sequenceIndex } != manifest.members.indices.toList() ||
            manifest.members.map { it.fileName }.distinct().size != manifest.members.size ||
            manifest.members.any { it.sizeBytes <= 0 || it.sizeBytes > manifest.totalBytes } ||
            manifest.members.sumOf { it.sizeBytes } != manifest.totalBytes) return false
        return manifest.members.all { member ->
            val page = File(file, member.fileName)
            member.fileName == page.name && page.canonicalFile.parentFile == file.canonicalFile &&
                page.isFile && page.length() == member.sizeBytes && detectImageMime(page) == member.mimeType
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
            try { output?.close() }
            finally {
                output = null
                java.nio.file.Files.deleteIfExists(partFile.toPath())
            }
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

        fun relativeArtifactDirectory(serverIdentity: String, userId: String, authorizationVersion: Long): String =
            sha256("$serverIdentity|$userId|$authorizationVersion") + "/artifacts"

        fun taskArtifactKey(resourceId: String, assetId: String, taskId: String): String =
            sha256("$resourceId:$assetId") + "-" + sha256(taskId).take(16)

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
