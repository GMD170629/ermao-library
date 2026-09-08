package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.infrastructure.toShared
import com.ermao.library.shared.modules.downloads.DownloadManagementItem

/** Account-owned task observation and commands; also used by Reader transitions. */
typealias AccountDownloads = com.ermao.library.features.downloads.application.DownloadActionsViewModel
typealias DownloadRecord = com.ermao.library.features.downloads.model.AndroidDownloadRecord
typealias DownloadStatus = com.ermao.library.features.downloads.model.AndroidDownloadStatus

@androidx.compose.runtime.Composable
fun downloadFailureMessage(code: String?): String =
    com.ermao.library.features.downloads.ui.downloadFailureSummary(code)

/** Maps Android catalog facts to the shared management policy input. */
fun downloadManagementItem(
    resourceId: String,
    record: AndroidDownloadRecord?,
    active: Boolean,
    available: Boolean,
    verified: Boolean = record?.verified == true,
): DownloadManagementItem = DownloadManagementItem(
    resourceId = resourceId,
    status = record?.status?.toShared(),
    verified = verified,
    active = active,
    available = available,
    failureCode = record?.errorCode,
)
