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
    if (!isSupportedNativeDownloadReader(readerType, format)) {
        return DownloadReaderEntryAction.ValidateStreamingAccess
    }
    return if (existing?.isReadable == true && localArtifactIsValid(existing)) {
        DownloadReaderEntryAction.ValidateCurrentArtifact
    } else {
        DownloadReaderEntryAction.OpenPreparation
    }
}

fun isSupportedNativeReflowable(readerType: String, format: String): Boolean =
    readerType.equals("reflowable", ignoreCase = true) &&
        format.trim().uppercase() in SUPPORTED_REFLOWABLE_FORMATS

fun isSupportedNativeDownloadReader(readerType: String, format: String): Boolean =
    isSupportedNativeReflowable(readerType, format) ||
        readerType.equals("comic", ignoreCase = true) && format.trim().equals("CBZ", ignoreCase = true)

private val SUPPORTED_REFLOWABLE_FORMATS = setOf("EPUB", "MOBI", "AZW", "AZW3", "PRC")
