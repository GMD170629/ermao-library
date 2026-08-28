package com.ermao.library.features.downloads.model

import com.ermao.library.shared.modules.reader.ReaderFormatSupport

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
    if (!ReaderFormatSupport.canReadOriginal(readerType, format)) {
        return if (ReaderFormatSupport.canOpenOnline(readerType, format)) {
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
