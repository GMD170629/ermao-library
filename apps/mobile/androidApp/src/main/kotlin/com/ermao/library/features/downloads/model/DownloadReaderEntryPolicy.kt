package com.ermao.library.features.downloads.model

import com.ermao.library.shared.modules.reader.ReaderFormatSupport
import com.ermao.library.shared.modules.reader.ReaderDeliveryMode

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
        return if (ReaderFormatSupport.deliveryMode(readerType, format) == ReaderDeliveryMode.Stream) {
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
