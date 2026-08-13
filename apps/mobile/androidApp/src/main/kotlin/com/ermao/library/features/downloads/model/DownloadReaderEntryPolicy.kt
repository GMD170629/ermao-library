package com.ermao.library.features.downloads.model

enum class DownloadReaderEntryAction {
    OpenPreparation,
    ValidateCurrentArtifact,
    ValidateStreamingAccess,
}

fun downloadReaderEntryAction(
    readerType: String,
    format: String,
    existing: AndroidDownloadRecord?,
    localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
): DownloadReaderEntryAction {
    val isEpub = readerType.equals("reflowable", true) && format.equals("EPUB", true)
    if (!isEpub) return DownloadReaderEntryAction.ValidateStreamingAccess
    return if (existing?.isReadable == true && localArtifactIsValid(existing)) {
        DownloadReaderEntryAction.ValidateCurrentArtifact
    } else {
        DownloadReaderEntryAction.OpenPreparation
    }
}
