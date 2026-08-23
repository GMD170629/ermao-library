package com.ermao.library.features.downloads.infrastructure

import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadByteSink
import com.ermao.library.shared.modules.downloads.DownloadByteSinkSession
import com.ermao.library.shared.modules.downloads.DownloadSinkRequest
import java.io.File
import java.io.FileOutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class AtomicDownloadFileSink(private val rootDirectory: File) : DownloadByteSink {
    override suspend fun begin(request: DownloadSinkRequest): DownloadByteSinkSession {
        require(request.resumeFromBytes == 0L) { "Android managed downloads do not support resume yet" }
        return begin(
            namespace = AndroidDownloadNamespace(
                request.namespace.serverIdentity,
                request.namespace.userId,
                request.namespace.authorizationVersion,
            ),
            resourceId = request.resourceId,
            assetId = request.assetId,
        )
    }

    suspend fun begin(
        namespace: AndroidDownloadNamespace,
        resourceId: String,
        assetId: String,
    ): Session = withContext(Dispatchers.IO) {
        require(resourceId.isNotBlank())
        require(assetId.isNotBlank())
        val namespaceKey = sha256("${namespace.serverIdentity}|${namespace.userId}|${namespace.authorizationVersion}")
        val artifactKey = sha256("$resourceId:$assetId")
        val relativeDirectory = "$namespaceKey/artifacts"
        val directory = File(rootDirectory, relativeDirectory).apply { mkdirs() }
        val part = File(directory, "$artifactKey.part")
        val final = File(directory, "$artifactKey.bin")
        // The first Android delivery restarts interrupted foreground transfers. It does not
        // advertise byte-range resume until the transfer gateway owns an If-Range contract.
        part.delete()
        Session(
            part,
            final,
            "$relativeDirectory/$artifactKey.bin",
            FileOutputStream(part, false),
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
        return file.isFile && file.length() > 0L
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
    ) : DownloadByteSinkSession {
        private var writtenBytes = 0L

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

        private fun abortInternal() {
            runCatching { output?.close() }
            output = null
            partFile.delete()
        }
    }
}
