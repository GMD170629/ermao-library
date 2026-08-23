package com.ermao.library.shared.modules.downloads.domain

data class ReaderAccessRequest(
    val namespace: DownloadNamespace,
    val resourceId: String,
    val readerType: DownloadReaderType,
    val isOnline: Boolean,
) {
    init {
        require(resourceId.isNotBlank())
    }
}

sealed interface ReaderAccessDecision {
    data object NeedsDownload : ReaderAccessDecision
    data object RemoteStream : ReaderAccessDecision
    data class LocalArtifact(val artifact: CompletedDownloadArtifact) : ReaderAccessDecision
    data class Unavailable(val reasonCode: String) : ReaderAccessDecision
}

class ReaderAccessPolicy {
    fun decide(
        request: ReaderAccessRequest,
        completedArtifacts: List<CompletedDownloadArtifact>,
    ): ReaderAccessDecision {
        val local = completedArtifacts.firstOrNull { artifact ->
            artifact.identity.namespace == request.namespace &&
                artifact.identity.resourceId == request.resourceId
        }
        if (local != null) return ReaderAccessDecision.LocalArtifact(local)
        return when (request.readerType) {
            DownloadReaderType.Reflowable -> ReaderAccessDecision.NeedsDownload
            DownloadReaderType.Pdf,
            DownloadReaderType.Comic,
            -> if (request.isOnline) {
                ReaderAccessDecision.RemoteStream
            } else {
                ReaderAccessDecision.Unavailable("OFFLINE_ARTIFACT_MISSING")
            }
            DownloadReaderType.Audio -> ReaderAccessDecision.Unavailable("READER_TYPE_NOT_SUPPORTED")
        }
    }
}
