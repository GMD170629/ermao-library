package com.ermao.library.features.content.model

import androidx.compose.runtime.Immutable
import kotlinx.serialization.Serializable

@Serializable
enum class LibraryScope { Books, Series, Authors }

@Serializable
enum class ContentSort { RecentAdded, RecentReading, Title, Author }

@Serializable
enum class ContentViewMode { Grid, List }

@Serializable
enum class ReadingFilter { Unread, Reading, Finished }

@Immutable
@Serializable
data class WorksFilters(
    val reading: ReadingFilter? = null,
) {
    val count: Int get() = if (reading == null) 0 else 1
}

@Immutable
@Serializable
data class BookCard(
    val id: String,
    val title: String,
    val author: String,
    val coverUrl: String,
    val progressPercent: Int?,
    val completed: Boolean? = null,
)

@Immutable
@Serializable
data class GroupingCard(
    val id: String,
    val name: String,
    val bookCount: Int,
    val representativeBooks: List<BookCard>,
)

@Immutable
@Serializable
data class ContinueReadingCard(
    val book: BookCard,
    val resourceTitle: String?,
    val positionLabel: String?,
    val lastReadAtEpochMillis: Long?,
    val resumeResourceId: String? = null,
)

@Immutable
@Serializable
data class HomeContent(
    val continueReading: ContinueReadingCard?,
    val recentReading: List<BookCard>,
    val recentAdded: List<BookCard>,
)

@Immutable
@Serializable
data class ResourceContent(
    val id: String,
    val sourceNodeId: String = "",
    val title: String,
    val format: String,
    val readerType: String = "reflowable",
    val description: String? = null,
    val importStatus: String = "READY",
    val importError: String? = null,
    val resourceIndex: Double? = null,
    val sortOrder: Int = 0,
    val publisher: String? = null,
    val publishedAt: String? = null,
    val language: String? = null,
    val isbn: String? = null,
    val identifier: String? = null,
    val narrator: String? = null,
    val pageCount: Int? = null,
    val chapterCount: Int? = null,
    val durationMillis: Long? = null,
    val trackCount: Int? = null,
    val metadataSource: String? = null,
    val kindleSendAvailable: Boolean = false,
    val assets: List<AssetContent> = emptyList(),
    val coverUrl: String = "",
    val sizeBytes: Long = 0,
    val progressPercent: Int?,
    val readable: Boolean,
    val selected: Boolean,
) {
    fun displayIndex(position: Int): String {
        val explicitIndex = resourceIndex?.takeIf { it.isFinite() && it > 0 }
        val value = when {
            explicitIndex == null -> (position + 1).toString()
            explicitIndex % 1.0 == 0.0 -> explicitIndex.toInt().toString()
            else -> explicitIndex.toString().trimEnd('0').trimEnd('.')
        }
        return value.padStart(2, '0')
    }
}

@Immutable
@Serializable
data class AssetContent(
    val id: String,
    val path: String,
    val sizeBytes: Long,
    val displaySize: String,
)

@Immutable
@Serializable
data class ReadingUnitContent(
    val id: String,
    val title: String,
    val progressPercent: Int? = null,
    val positionLabel: String? = null,
    val href: String? = null,
    val sortOrder: Int = 0,
    val readingOrderPosition: Int? = null,
    val readingState: ChapterReadingState = ChapterReadingState.Unread,
)

@Serializable
enum class ChapterReadingState { Current, Read, Unread }

@Immutable
@Serializable
data class BookDetailContent(
    val book: BookCard,
    val seriesId: String?,
    val seriesName: String?,
    val seriesIndex: Double? = null,
    val authorFacetId: String?,
    val description: String?,
    val tags: List<String>,
    val resources: List<ResourceContent>,
    val selectedResourceId: String?,
    val completed: Boolean = false,
    val readingUnits: List<ReadingUnitContent> = emptyList(),
    val continueResourceId: String? = null,
) {
    val continueResource: ResourceContent? get() = resources.firstOrNull { it.id == continueResourceId }
    val hasDescription: Boolean get() = !description.isNullOrBlank()
    val showsResourcePicker: Boolean get() = resources.size > 1
    fun supportsChapterDirectory(resourceId: String?): Boolean =
        resourceId != null &&
            resources.firstOrNull { it.id == resourceId }
                ?.readerType.equals("reflowable", ignoreCase = true) &&
            readingUnits.isNotEmpty()
}
