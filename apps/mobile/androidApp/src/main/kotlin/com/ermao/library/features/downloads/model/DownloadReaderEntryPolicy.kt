package com.ermao.library.features.downloads.model

enum class DownloadReaderEntryAction {
    OpenLocalArtifact,
    OpenServerReader,
    ValidateUnsupportedAccess,
}

fun downloadReaderEntryAction(
    readerType: String,
    format: String,
    existing: AndroidDownloadRecord?,
    localArtifactIsValid: (AndroidDownloadRecord) -> Boolean,
): DownloadReaderEntryAction {
    if (!isSupportedNativeDownloadReader(readerType, format)) {
        return if (isSupportedNativeReaderEntry(readerType, format)) {
            DownloadReaderEntryAction.OpenServerReader
        } else {
            DownloadReaderEntryAction.ValidateUnsupportedAccess
        }
    }
    return if (existing?.isReadable == true && localArtifactIsValid(existing)) {
        DownloadReaderEntryAction.OpenLocalArtifact
    } else {
        DownloadReaderEntryAction.OpenServerReader
    }
}

fun isSupportedNativeReflowable(readerType: String, format: String): Boolean =
    readerType.equals("reflowable", ignoreCase = true) &&
        format.trim().uppercase() in SUPPORTED_REFLOWABLE_FORMATS

fun isSupportedNativeDownloadReader(readerType: String, format: String): Boolean =
    isSupportedNativeReflowable(readerType, format) ||
        (readerType.equals("comic", ignoreCase = true) && format.trim().uppercase() in SUPPORTED_COMIC_FORMATS) ||
        (readerType.equals("pdf", ignoreCase = true) && format.trim().equals("PDF", ignoreCase = true))

fun isSupportedNativeReaderEntry(readerType: String, format: String): Boolean =
    isSupportedNativeReflowable(readerType, format) ||
        readerType.equals("comic", ignoreCase = true) ||
        readerType.equals("pdf", ignoreCase = true)

private val SUPPORTED_REFLOWABLE_FORMATS = setOf("EPUB", "MOBI", "AZW", "AZW3", "PRC", "TXT", "FB2")
private val SUPPORTED_COMIC_FORMATS = setOf("CBZ", "ZIP", "CBR", "RAR", "IMAGE_DIR")
