package com.ermao.library.shared.modules.administrativesettings.domain

data class Library(
    val id: String,
    val name: String,
    val rootPath: String,
    val shelfId: String?,
    val enabled: Boolean,
    val mediaKindPolicy: MediaKindPolicy,
    val ignorePatterns: String?,
    val ignoreHidden: Boolean,
    val minimumFileSizeBytes: Long,
    val description: String?,
    val createdAt: String,
    val updatedAt: String,
)

data class Libraries(
    val folders: List<Library>,
    val monitorRoot: String?,
    val lastUploadTargetPath: String?,
    val lastDownloadTargetPath: String?,
)

data class LibraryDraft(
    val rootPath: String,
    val name: String?,
    val shelfId: String?,
    val enabled: Boolean,
    val mediaKindPolicy: MediaKindPolicy,
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

enum class ImportTaskStatus(val wireValue: String) {
    Pending("PENDING"),
    Parsing("PARSING"),
    Completed("COMPLETED"),
    Failed("FAILED"),
}

data class ImportTaskFilter(
    val status: ImportTaskStatus? = null,
    val keyword: String? = null,
    val page: Int = 1,
    val pageSize: Int = 20,
)

data class ImportTask(
    val id: String,
    val libraryId: String?,
    val workId: String?,
    val volumeId: String?,
    val origin: String,
    val mediaKindPolicy: MediaKindPolicy,
    val status: ImportTaskStatus,
    val originalName: String?,
    val requestedTitle: String?,
    val requestedAuthor: String?,
    val sourcePath: String,
    val taskKind: String,
    val assetCount: Int,
    val processedAssetCount: Int,
    val progress: Int,
    val durationMilliseconds: Long,
    val errorCode: String?,
    val errorSummary: String?,
    val retryable: Boolean,
    val attempts: Int,
    val startedAt: String?,
    val finishedAt: String?,
    val createdAt: String,
    val updatedAt: String,
    val sourceFileExists: Boolean,
)

data class ImportTaskSummary(
    val completed: Int,
    val failed: Int,
)

data class ImportTaskPage(
    val tasks: List<ImportTask>,
    val summary: ImportTaskSummary,
    val pageInfo: PageInfo,
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
    val stabilityCheckEnabled: Boolean,
    val stabilitySeconds: Double,
    val allowedExtensions: List<String>,
    val ignorePatterns: String,
)
