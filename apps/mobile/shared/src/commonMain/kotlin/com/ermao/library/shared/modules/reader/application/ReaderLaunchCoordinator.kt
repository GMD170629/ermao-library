package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.DownloadBootstrapGateway
import com.ermao.library.shared.modules.downloads.DownloadBootstrapFailure
import com.ermao.library.shared.modules.downloads.DownloadBootstrapSuccess
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.DownloadTask
import com.ermao.library.shared.modules.reader.domain.ReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.ReaderDeliveryMode
import com.ermao.library.shared.modules.reader.domain.ReaderFormatSupport
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

    fun progress(received: Long, total: Long): Double {
        require(total > 0 && received in 0..total)
        return received.toDouble() / total.toDouble()
    }
}

sealed interface ReaderLaunch {
    data class Stream(val descriptor: DownloadDescriptor) : ReaderLaunch {
        init {
            require(
                ReaderFormatSupport.deliveryMode(
                    descriptor.readerType.name,
                    descriptor.format,
                ) == ReaderDeliveryMode.Stream,
            ) { "Reader streaming is reserved for PDF and comic resources" }
        }
    }
    data class Local(val artifact: CompletedDownloadArtifact) : ReaderLaunch
    data class Download(val descriptor: DownloadDescriptor) : ReaderLaunch
    data class Unavailable(val code: ReaderErrorCode) : ReaderLaunch
}

/** Resolves fresh authorization and exact asset identity when reachable.
 * Only non-authoritative connectivity failures may reuse a verified artifact from the active namespace.
 */
class ReaderLaunchCoordinator(
    private val catalog: DownloadCatalogRepository,
    private val gateway: DownloadBootstrapGateway,
) {
    @Throws(Exception::class)
    suspend fun prepare(context: DownloadRequestContext, resourceId: String): ReaderLaunch {
        val localArtifacts = catalog.listArtifacts(context.namespace)
            .filter { it.identity.resourceId == resourceId }
        return when (val result = gateway.load(context, resourceId)) {
            is DownloadBootstrapFailure -> {
                val local = localArtifacts
                    .filter { it.descriptor.deliveryMode() == ReaderDeliveryMode.DownloadOriginal }
                    .maxByOrNull { it.completedAtEpochMillis }
                if (result.error.kind.allowsVerifiedOfflineReaderFallback() && local != null) {
                    local(local)
                } else {
                    ReaderLaunch.Unavailable(
                        readerErrorCodeForFailure(result.error.code, false),
                    )
                }
            }
            is DownloadBootstrapSuccess -> {
                val descriptor = result.bootstrap.descriptor
                val localFailure = ReaderAdmission.localFailure(descriptor.format, descriptor.totalBytes)
                val local = localArtifacts
                    .filter { descriptor.matches(it.descriptor) }
                    .maxByOrNull { it.completedAtEpochMillis }
                when {
                    localFailure != null -> ReaderLaunch.Unavailable(localFailure)
                    local != null -> local(local)
                    descriptor.deliveryMode() == ReaderDeliveryMode.DownloadOriginal -> ReaderLaunch.Download(descriptor)
                    descriptor.deliveryMode() == ReaderDeliveryMode.Stream -> ReaderLaunch.Stream(descriptor)
                    else -> ReaderLaunch.Unavailable(ReaderErrorCode.UnsupportedFormat)
                }
            }
        }
    }

    @Throws(Exception::class)
    suspend fun complete(descriptor: DownloadDescriptor): ReaderLaunch {
        val candidates = catalog.listArtifacts(descriptor.identity.namespace)
            .filter { it.identity.resourceId == descriptor.identity.resourceId }
        val artifact = candidates.filter { descriptor.matches(it.descriptor) }
            .maxByOrNull { it.completedAtEpochMillis }
            ?: return ReaderLaunch.Unavailable(
                if (candidates.isEmpty()) ReaderErrorCode.ResourceMissing else ReaderErrorCode.PublicationChanged,
            )
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

    private fun DownloadDescriptor.matches(candidate: DownloadDescriptor): Boolean =
        DownloadTask("reader-validation", this).matchesDescriptor(candidate)

    private fun DownloadDescriptor.deliveryMode(): ReaderDeliveryMode =
        ReaderFormatSupport.deliveryMode(readerType.name, format)
}

private fun AppErrorKind.allowsVerifiedOfflineReaderFallback(): Boolean = this in setOf(
    AppErrorKind.NetworkUnavailable,
    AppErrorKind.Timeout,
    AppErrorKind.TlsFailure,
    AppErrorKind.ServiceUnavailable,
    AppErrorKind.ServerFailure,
)
