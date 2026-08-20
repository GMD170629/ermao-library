package com.ermao.library.shared.modules.workmanagement.domain

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerProfile

data class WorkManagementContext(
    val profile: ServerProfile,
    val namespace: PrivateDataNamespace,
) {
    init {
        require(profile.serverIdentity == namespace.serverIdentity)
    }
}

enum class WorkManagementErrorKind {
    Unauthorized,
    Forbidden,
    Inaccessible,
    Conflict,
    Validation,
    Offline,
    Server,
    Protocol,
    Storage,
}

data class WorkManagementError(
    val kind: WorkManagementErrorKind,
    val code: String,
    val fieldErrors: Map<String, List<String>> = emptyMap(),
)

sealed interface WorkManagementResult<out T> {
    data class Content<T>(val value: T) : WorkManagementResult<T>
    data class Failure(val error: WorkManagementError) : WorkManagementResult<Nothing>
}

data class WorkMetadataDraft(
    val title: String,
    val author: String,
    val description: String,
    val seriesName: String?,
    val seriesIndex: Double?,
    val tags: List<String>,
) {
    init {
        require(title.isNotBlank())
        require(seriesIndex == null || seriesIndex.isFinite())
    }
}

data class VolumeMetadataDraft(
    val publisher: String?,
    val language: String?,
    val isbn: String?,
    val identifier: String?,
    val narrator: String?,
)

enum class ManagedMediaKind(val wireValue: String) {
    Ebook("EBOOK"),
    Comic("COMIC"),
    Audiobook("AUDIOBOOK"),
}

enum class ManagedReadingStatus(val wireValue: String) {
    Unread("UNREAD"),
    Finished("FINISHED"),
}

data class WorkMutationOutcome(
    val workId: String,
    val operationId: String? = null,
)

data class MetadataProvider(
    val id: String,
    val name: String,
    val enabled: Boolean,
    val mediaKinds: Set<ManagedMediaKind>,
)

enum class MetadataField(val wireValue: String) {
    Cover("coverUrl"),
    Title("title"),
    Author("author"),
    Description("description"),
    Tags("tags"),
    SeriesName("seriesName"),
    Publisher("publisher"),
    PublishedAt("publishedAt"),
    Language("language"),
    Isbn("isbn"),
}

data class MetadataCandidate(
    val id: String,
    val source: String,
    val title: String?,
    val author: String?,
    val description: String?,
    val tags: List<String>,
    val seriesName: String?,
    val publisher: String?,
    val publishedAt: String?,
    val language: String?,
    val isbn: String?,
    val coverUrl: String?,
    val confidence: Double,
)

data class MetadataSearchResult(
    val candidates: List<MetadataCandidate>,
    val message: String?,
)

data class CoverUpload(
    val fileName: String,
    val mimeType: String,
    val bytes: ByteArray,
) {
    init {
        require(fileName.isNotBlank())
        require(mimeType in SUPPORTED_COVER_MIME_TYPES)
        require(bytes.isNotEmpty())
    }

    companion object {
        val SUPPORTED_COVER_MIME_TYPES = setOf("image/jpeg", "image/png", "image/webp")
    }
}

data class KindleSettings(
    val recipientEmail: String,
    val smtpConfigured: Boolean,
    val senderEmail: String,
) {
    val ready: Boolean = recipientEmail.isNotBlank() && smtpConfigured && senderEmail.isNotBlank()
}

data class KindleSendOutcome(val alreadyQueued: Boolean)
