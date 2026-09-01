package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.DownloadBootstrapGateway
import com.ermao.library.shared.modules.downloads.DownloadBootstrapFailure
import com.ermao.library.shared.modules.downloads.DownloadBootstrapSuccess
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.domain.matchesVersion
import com.ermao.library.shared.modules.reader.domain.ReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.ReaderDeliveryMode
import com.ermao.library.shared.modules.reader.domain.ReaderFormatSupport
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFailure
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFormat
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId
import com.ermao.library.shared.modules.reader.domain.readerErrorCodeForFailure

/** Admission is not an engine allocation or successful-opening guarantee. */
object ReaderAdmission {
    val maximumPublicationBytes: Long =
        ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES)

    fun accepts(bytes: Long): Boolean = bytes in 0..maximumPublicationBytes

    fun localFailure(format: String, bytes: Long): ReaderErrorCode? = when {
        !accepts(bytes) -> ReaderErrorCode.PublicationTooLarge
        bytes > localMemoryBudget(format) ->
            ReaderErrorCode.OutOfMemoryRisk
        else -> null
    }

    fun localSafetyFailure(format: String, bytes: Long): ReaderSafetyFailure? = when {
        !accepts(bytes) ->
            ReaderSafetyFacade().failureFor(ReaderSafetyRuleId.COMMON_ORIGINAL_MAX_BYTES)
        ReaderSafetyPolicy.formatPolicy(format)?.id == ReaderSafetyFormat.TXT &&
            bytes > ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.TXT_MEMORY_MAX_BYTES) ->
            ReaderSafetyFacade().failureFor(ReaderSafetyRuleId.TXT_MEMORY_BUDGET)
        else -> null
    }

    private fun localMemoryBudget(format: String): Long =
        when (ReaderSafetyPolicy.formatPolicy(format)?.id) {
            ReaderSafetyFormat.TXT ->
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.TXT_MEMORY_MAX_BYTES)
            else -> maximumPublicationBytes
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
    data class Unavailable(
        val code: ReaderErrorCode,
        val safetyFailure: ReaderSafetyFailure? = null,
    ) : ReaderLaunch
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
                    .filter { descriptor.matchesVersion(it.descriptor) }
                    .maxByOrNull { it.completedAtEpochMillis }
                when {
                    localFailure != null -> ReaderLaunch.Unavailable(
                        localFailure,
                        ReaderAdmission.localSafetyFailure(descriptor.format, descriptor.totalBytes),
                    )
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
        val artifact = candidates.filter { descriptor.matchesVersion(it.descriptor) }
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
            failure != null -> ReaderLaunch.Unavailable(
                failure,
                ReaderAdmission.localSafetyFailure(descriptor.format, descriptor.totalBytes),
            )
            !ReaderFormatSupport.canReadOriginal(descriptor.readerType.name.lowercase(), descriptor.format) ->
                ReaderLaunch.Unavailable(ReaderErrorCode.UnsupportedFormat)
            else -> ReaderLaunch.Local(artifact)
        }
    }

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
