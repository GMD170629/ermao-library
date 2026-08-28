package com.ermao.library.shared.modules.workmanagement.domain

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerProfile

data class BookManagementContext(
    val profile: ServerProfile,
    val namespace: PrivateDataNamespace,
) {
    init { require(profile.serverIdentity == namespace.serverIdentity) }
}

enum class WorkManagementErrorKind {
    Unauthorized,
    Forbidden,
    Inaccessible,
    Unavailable,
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

data class BookMetadataDraft(
    val title: String,
    val author: String?,
    val description: String?,
    val seriesName: String?,
    val seriesIndex: Double?,
    val tags: List<String> = emptyList(),
    val originalTags: List<String> = emptyList(),
) {
    init {
        require(title.isNotBlank())
        require(seriesIndex == null || seriesIndex.isFinite())
    }
}

data class ResourceMetadataDraft(
    val title: String? = null,
    val description: String? = null,
    val publisher: String? = null,
    val publishedAt: String? = null,
    val language: String? = null,
    val isbn: String? = null,
    val identifier: String? = null,
    val narrator: String? = null,
    val abridged: Boolean? = null,
    val resourceIndex: Double? = null,
)

data class BookDeletionOutcome(val deletedBookIds: List<String>)

enum class ManagedReadingStatus(val wireValue: String) {
    Unread("UNREAD"),
    Finished("FINISHED"),
}

data class BookMutationOutcome(
    val bookId: String,
    val resourceId: String,
)

data class CoverMutationOutcome(
    val resourceId: String,
    val coverUrl: String,
)

data class MetadataProvider(
    val id: String,
    val name: String,
    val enabled: Boolean,
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
    val seriesIndex: Double? = null,
    val identifier: String? = null,
    val narrator: String? = null,
    val abridged: Boolean? = null,
    val resourceIndex: Double? = null,
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
        require(bytes.size <= MAXIMUM_COVER_BYTES)
    }

    companion object {
        const val MAXIMUM_COVER_BYTES = 10 * 1024 * 1024
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
