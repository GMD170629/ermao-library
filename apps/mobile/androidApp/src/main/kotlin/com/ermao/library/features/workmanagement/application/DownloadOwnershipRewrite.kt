package com.ermao.library.features.workmanagement.application

internal const val STRUCTURAL_MOVE_VERSION_SOURCE_KEY = "__implicit__"

internal data class DownloadOwnershipRewrite(
    val targetWorkId: String,
    val targetVersionId: String,
    val targetVersionSourceKey: String,
    val targetVersionSourceName: String?,
    val targetVersionCompleted: Boolean?,
    val targetWorkTitle: String,
    val targetWorkAuthor: String?,
    val targetCoverApiPath: String?,
)

/**
 * Split/transfer rewrite the completed download onto the server's target Work and
 * LibraryVersion. [targetVersionId] is the current `targetMediaVersionId` wire field.
 */
internal fun downloadOwnershipRewriteForStructuralMove(
    targetWorkId: String?,
    targetVersionId: String?,
    targetWorkTitle: String,
    targetWorkAuthor: String?,
    targetCoverApiPath: String?,
): DownloadOwnershipRewrite? {
    val workId = targetWorkId?.trim().orEmpty()
    val versionId = targetVersionId?.trim().orEmpty()
    if (workId.isEmpty() || versionId.isEmpty() || targetWorkTitle.isBlank()) return null
    return DownloadOwnershipRewrite(
        targetWorkId = workId,
        targetVersionId = versionId,
        targetVersionSourceKey = STRUCTURAL_MOVE_VERSION_SOURCE_KEY,
        targetVersionSourceName = null,
        targetVersionCompleted = null,
        targetWorkTitle = targetWorkTitle,
        targetWorkAuthor = targetWorkAuthor,
        targetCoverApiPath = targetCoverApiPath,
    )
}
