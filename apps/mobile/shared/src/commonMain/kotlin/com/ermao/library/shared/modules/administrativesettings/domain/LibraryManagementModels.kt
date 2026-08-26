package com.ermao.library.shared.modules.administrativesettings.domain

data class Library(
    val id: String,
    val name: String,
    val rootPath: String,
    val organizationMode: LibraryOrganizationMode,
    val enabled: Boolean,
    val ignorePatterns: String?,
    val ignoreHidden: Boolean,
    val minimumFileSizeBytes: Long,
    val description: String?,
    val createdAt: String,
    val updatedAt: String,
)

data class Libraries(
    val libraries: List<Library>,
    val lastUploadTargetPath: String?,
    val lastDownloadTargetPath: String?,
)

enum class LibraryOrganizationMode(val wireValue: String) {
    Flat("FLAT"),
    Volumes("VOLUMES"),
    Audiobook("AUDIOBOOK"),
}

data class LibraryDraft(
    val rootPath: String,
    val name: String?,
    val organizationMode: LibraryOrganizationMode,
    val enabled: Boolean,
    val ignorePatterns: String?,
    val ignoreHidden: Boolean,
    val minimumFileSizeBytes: Long,
    val description: String?,
)

data class DirectoryChild(
    val name: String,
    val path: String,
    val readable: Boolean,
)

data class DirectoryNode(
    val name: String,
    val path: String,
    val readable: Boolean,
    val error: String?,
    val children: List<DirectoryChild>,
)

enum class ImportTaskState(val wireValue: String) {
    Queued("QUEUED"),
    Running("RUNNING"),
    Succeeded("SUCCEEDED"),
    Failed("FAILED"),
}

data class ImportTaskFilter(
    val state: ImportTaskState? = null,
    val keyword: String? = null,
    val page: Int = 1,
    val pageSize: Int = 20,
)

data class ImportTask(
    val id: String,
    val kind: String,
    val libraryId: String,
    val libraryName: String?,
    val resourceId: String?,
    val resourceTitle: String?,
    val sourceNodeId: String?,
    val sourceName: String?,
    val sourceRelativePath: String?,
    val bookTitle: String?,
    val role: String?,
    val state: ImportTaskState,
    val errorSummary: String?,
    val createdAt: String,
    val startedAt: String?,
    val finishedAt: String?,
)

data class ImportTaskPage(
    val tasks: List<ImportTask>,
    val pageInfo: PageInfo,
    val completed: Int,
    val failed: Int,
)

data class ImportTaskLog(
    val id: String,
    val level: String,
    /** Server log content is display-only and must never control a program branch. */
    val message: String,
    val createdAt: String?,
)

data class ImportTaskLogPage(
    val logs: List<ImportTaskLog>,
    val pageInfo: PageInfo,
)

data class ImportTaskDeletion(
    val id: String,
    val deleted: Boolean,
)

enum class ImportScanStatus(val wireValue: String) {
    Pending("PENDING"),
    Running("RUNNING"),
    Completed("COMPLETED"),
    Failed("FAILED"),
    Cancelled("CANCELLED"),
}

data class ImportScanJob(
    val id: String,
    val libraryId: String?,
    val rootPath: String,
    val trigger: String,
    val status: ImportScanStatus,
    val directoriesScanned: Int,
    val filesScanned: Int,
    val candidatesFound: Int,
    val queuedCount: Int,
    val skippedCount: Int,
    val errorCount: Int,
    val restartCount: Int,
    val startedAt: String?,
    val heartbeatAt: String?,
    val finishedAt: String?,
    val createdAt: String,
    val updatedAt: String,
)

data class ImportRescanRequest(
    val requestedAt: String,
    val jobs: List<ImportScanJob>,
)

data class ImportPreferences(
    val allowedExtensions: List<String>,
    val ignorePatterns: String,
)
