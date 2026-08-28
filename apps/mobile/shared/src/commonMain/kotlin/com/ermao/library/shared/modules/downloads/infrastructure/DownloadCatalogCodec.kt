package com.ermao.library.shared.modules.downloads.infrastructure

import com.ermao.library.shared.modules.downloads.domain.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.domain.DownloadArtifactKind
import com.ermao.library.shared.modules.downloads.domain.DownloadBundleMember
import com.ermao.library.shared.modules.downloads.domain.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.domain.DownloadIdentity
import com.ermao.library.shared.modules.downloads.domain.DownloadNamespace
import com.ermao.library.shared.modules.downloads.domain.DownloadReaderType
import com.ermao.library.shared.modules.downloads.domain.DownloadSource
import com.ermao.library.shared.modules.downloads.domain.DownloadTask
import com.ermao.library.shared.modules.downloads.domain.DownloadTaskStatus
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** Validated disk boundary shared by native catalog adapters. Never stores session credentials. */
object DownloadCatalogCodec {
    private val json = Json { ignoreUnknownKeys = false }

    fun encode(task: DownloadTask): String = json.encodeToString(TaskRecord.serializer(), TaskRecord.from(task))

    @Throws(IllegalArgumentException::class)
    fun decode(serialized: String): DownloadTask {
        require(serialized.length <= 8 * 1024 * 1024)
        return json.decodeFromString(TaskRecord.serializer(), serialized).toTask()
    }
}

@Serializable
private data class MemberRecord(val assetId: String, val sequence: Int, val path: String, val mime: String, val bytes: Long, val modifiedAt: Long? = null) {
    fun toMember() = DownloadBundleMember(assetId, sequence, DownloadSource(path, mime, bytes, modifiedAt))
    companion object {
        fun from(member: DownloadBundleMember) = MemberRecord(member.assetId, member.sequenceIndex, member.source.apiPath, member.source.mimeType, member.source.totalBytes, member.source.sourceModifiedAtMillis)
    }
}

@Serializable
private data class TaskRecord(
    val version: Int = 1,
    val id: String,
    val server: String, val user: String, val authorizationVersion: Long,
    val bookId: String, val resourceId: String, val assetId: String,
    val bookTitle: String, val author: String?, val cover: String?, val resourceTitle: String,
    val format: String, val readerType: String, val artifactKind: String,
    val resourceIndex: Double?, val sortOrder: Int?, val members: List<MemberRecord>,
    val status: String, val transferredBytes: Long, val failureCode: String?,
    val localReference: String?, val completedAt: Long?, val lastOpenedAt: Long?,
) {
    fun toTask(): DownloadTask {
        require(version == 1 && members.isNotEmpty())
        val mappedMembers = members.map(MemberRecord::toMember)
        val descriptor = DownloadDescriptor(
            identity = DownloadIdentity(DownloadNamespace(server, user, authorizationVersion), bookId, resourceId, assetId),
            bookTitle = bookTitle, bookAuthor = author, coverApiPath = cover, resourceTitle = resourceTitle,
            format = format, readerType = DownloadReaderType.valueOf(readerType), source = mappedMembers.first().source,
            resourceIndex = resourceIndex, resourceSortOrder = sortOrder,
            artifactKind = DownloadArtifactKind.valueOf(artifactKind),
            members = if (DownloadArtifactKind.valueOf(artifactKind) == DownloadArtifactKind.SingleOriginalAsset) emptyList() else mappedMembers,
        )
        val artifact = localReference?.let { CompletedDownloadArtifact(descriptor, it, descriptor.totalBytes, requireNotNull(completedAt), lastOpenedAt) }
        require((status == DownloadTaskStatus.Completed.name) == (artifact != null))
        require(transferredBytes in 0..descriptor.totalBytes)
        return DownloadTask(id, descriptor, DownloadTaskStatus.valueOf(status), transferredBytes, failureCode, artifact)
    }
    companion object {
        fun from(task: DownloadTask): TaskRecord {
            val d = task.descriptor
            val identity = d.identity
            return TaskRecord(id = task.id, server = identity.namespace.serverIdentity, user = identity.namespace.userId,
                authorizationVersion = identity.namespace.authorizationVersion,
                bookId = identity.bookId, resourceId = identity.resourceId, assetId = identity.assetId,
                bookTitle = d.bookTitle, author = d.bookAuthor, cover = d.coverApiPath, resourceTitle = d.resourceTitle,
                format = d.format, readerType = d.readerType.name, artifactKind = d.artifactKind.name,
                resourceIndex = d.resourceIndex, sortOrder = d.resourceSortOrder, members = d.bundleMembers.map(MemberRecord::from),
                status = task.status.name, transferredBytes = task.transferredBytes, failureCode = task.failureCode,
                localReference = task.artifact?.localReference, completedAt = task.artifact?.completedAtEpochMillis,
                lastOpenedAt = task.artifact?.lastOpenedAtEpochMillis)
        }
    }
}
