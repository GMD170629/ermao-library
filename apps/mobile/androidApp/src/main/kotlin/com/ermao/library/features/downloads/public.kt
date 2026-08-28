package com.ermao.library.features.downloads

/** Account-owned task observation and commands; also used by Reader transitions. */
typealias AccountDownloads = com.ermao.library.features.downloads.application.DownloadActionsViewModel
typealias DownloadRecord = com.ermao.library.features.downloads.model.AndroidDownloadRecord
typealias DownloadStatus = com.ermao.library.features.downloads.model.AndroidDownloadStatus

@androidx.compose.runtime.Composable
fun downloadFailureMessage(code: String?): String =
    com.ermao.library.features.downloads.ui.downloadFailureSummary(code)
