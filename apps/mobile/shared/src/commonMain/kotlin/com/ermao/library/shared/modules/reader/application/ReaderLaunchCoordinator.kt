package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.DownloadBootstrapGateway
import com.ermao.library.shared.modules.downloads.DownloadBootstrapFailure
import com.ermao.library.shared.modules.downloads.DownloadBootstrapSuccess
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.DownloadTask
import com.ermao.library.shared.modules.reader.domain.ReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.ReaderFormatSupport
import com.ermao.library.shared.modules.reader.domain.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.domain.readerErrorCodeForFailure

/** Admission is not an engine allocation or successful-opening guarantee. */
object ReaderAdmission {
    const val maximumPublicationBytes: Long = 2L * 1024 * 1024 * 1024

    fun accepts(bytes: Long): Boolean = bytes in 0..maximumPublicationBytes

    fun localFailure(format: String, bytes: Long): ReaderErrorCode? = when {
        !accepts(bytes) -> ReaderErrorCode.PublicationTooLarge
        // Both TXT adapters cross the Kotlin String/ByteArray boundary. Do not attempt
        // an allocation which is known to be unrepresentable, even on 64-bit devices.
        format.lowercase() in setOf("txt", "fb2") && bytes > Int.MAX_VALUE - 8L ->
            ReaderErrorCode.OutOfMemoryRisk
        else -> null
    }

    fun permitsDownload(failure: ReaderErrorCode): Boolean =
        failure == ReaderErrorCode.OnlineLimit || failure == ReaderErrorCode.RangeUnsupported

    fun progress(received: Long, total: Long): Double {
        require(total > 0 && received in 0..total)
        return received.toDouble() / total.toDouble()
    }
}

sealed interface ReaderLaunch {
    data class Online(val descriptor: DownloadDescriptor) : ReaderLaunch
    data class Local(val artifact: CompletedDownloadArtifact) : ReaderLaunch
    data class Download(val descriptor: DownloadDescriptor, val reason: ReaderErrorCode) : ReaderLaunch
    data class Unavailable(val code: ReaderErrorCode) : ReaderLaunch
}

/** One launch owns one fallback decision. Transfer ownership remains in Downloads. */
class ReaderLaunchCoordinator(
    private val catalog: DownloadCatalogRepository,
    private val gateway: DownloadBootstrapGateway,
) {
    private var fallbackSelected = false

    @Throws(Exception::class)
    suspend fun prepare(context: DownloadRequestContext, resourceId: String): ReaderLaunch {
        val local = catalog.listArtifacts(context.namespace)
            .filter { it.identity.resourceId == resourceId }
            .maxByOrNull { it.completedAtEpochMillis }
        if (local != null) return local(local)
        return when (val result = gateway.load(context, resourceId)) {
            is DownloadBootstrapFailure -> ReaderLaunch.Unavailable(
                readerErrorCodeForFailure(result.error.code, false),
            )
            is DownloadBootstrapSuccess -> {
                val descriptor = result.bootstrap.descriptor
                when {
                    !ReaderAdmission.accepts(descriptor.totalBytes) ->
                        ReaderLaunch.Unavailable(ReaderErrorCode.PublicationTooLarge)
                    !ReaderFormatSupport.canOpenOnline(descriptor.readerType.name.lowercase(), descriptor.format) ->
                        ReaderLaunch.Unavailable(ReaderErrorCode.UnsupportedFormat)
                    else -> ReaderLaunch.Online(descriptor)
                }
            }
        }
    }

    fun fallback(descriptor: DownloadDescriptor, failure: ReaderErrorCode): ReaderLaunch {
        if (fallbackSelected || !ReaderAdmission.permitsDownload(failure)) return ReaderLaunch.Unavailable(failure)
        val localFailure = ReaderAdmission.localFailure(descriptor.format, descriptor.totalBytes)
        if (localFailure != null) return ReaderLaunch.Unavailable(localFailure)
        if (ReaderSourceFormat.fromWireValue(descriptor.format) == null ||
            !ReaderFormatSupport.canReadOriginal(descriptor.readerType.name.lowercase(), descriptor.format)) {
            return ReaderLaunch.Unavailable(ReaderErrorCode.UnsupportedFormat)
        }
        fallbackSelected = true
        return ReaderLaunch.Download(descriptor, failure)
    }

    fun fallbackCode(descriptor: DownloadDescriptor, failureCode: String): ReaderLaunch =
        fallback(descriptor, readerErrorCodeForFailure(failureCode, false))

    @Throws(Exception::class)
    suspend fun complete(descriptor: DownloadDescriptor): ReaderLaunch {
        val artifact = catalog.listArtifacts(descriptor.identity.namespace)
            .firstOrNull { it.identity.resourceId == descriptor.identity.resourceId }
            ?: return ReaderLaunch.Unavailable(ReaderErrorCode.ResourceMissing)
        if (!DownloadTask("reader-validation", descriptor).matchesDescriptor(artifact.descriptor)) {
            return ReaderLaunch.Unavailable(ReaderErrorCode.PublicationChanged)
        }
        return local(artifact)
    }

    private fun local(artifact: CompletedDownloadArtifact): ReaderLaunch {
        val descriptor = artifact.descriptor
        val failure = ReaderAdmission.localFailure(descriptor.format, descriptor.totalBytes)
        return when {
            failure != null -> ReaderLaunch.Unavailable(failure)
            !ReaderFormatSupport.canReadOriginal(descriptor.readerType.name.lowercase(), descriptor.format) ->
                ReaderLaunch.Unavailable(ReaderErrorCode.UnsupportedFormat)
            else -> ReaderLaunch.Local(artifact)
        }
    }
}
