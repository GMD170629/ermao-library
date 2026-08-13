package com.ermao.library.features.content.model

import androidx.compose.runtime.Immutable
import kotlinx.serialization.Serializable

@Serializable
enum class LibraryScope { Works, Series, Authors }

@Serializable
enum class ContentSort { RecentAdded, RecentReading, Title, Author }

@Serializable
enum class ContentViewMode { Grid, List }

@Serializable
enum class MediaFilter { Ebook, Comic, Audiobook }

@Serializable
enum class ReadingFilter { Unread, Reading, Finished }

@Immutable
@Serializable
data class WorksFilters(
    val media: Set<MediaFilter> = emptySet(),
    val reading: Set<ReadingFilter> = emptySet(),
    val downloadedOnly: Boolean = false,
) {
    val count: Int get() = media.size + reading.size + if (downloadedOnly) 1 else 0
}

@Immutable
@Serializable
data class WorkCard(
    val id: String,
    val title: String,
    val author: String,
    val coverUrl: String,
    val mediaKinds: List<String>,
    val progressPercent: Int?,
)

@Immutable
@Serializable
data class GroupingCard(
    val id: String,
    val name: String,
    val workCount: Int,
    val representativeWorks: List<WorkCard>,
)

@Immutable
@Serializable
data class ContinueReadingCard(
    val work: WorkCard,
    val volumeTitle: String?,
    val positionLabel: String?,
    val lastReadLabel: String?,
)

@Immutable
@Serializable
data class HomeContent(
    val continueReading: ContinueReadingCard?,
    val recentReading: List<WorkCard>,
    val recentAdded: List<WorkCard>,
)

@Serializable
enum class ContentFreshness { Fresh, Cached, Stale }

@Immutable
@Serializable
data class VolumeContent(
    val id: String,
    val title: String,
    val format: String,
    val readerType: String = "reflowable",
    val volumeIndex: Double? = null,
    val coverUrl: String = "",
    val sizeBytes: Long = 0,
    val progressPercent: Int?,
    val readable: Boolean,
    val selected: Boolean,
) {
    fun displayIndex(position: Int): String {
        val explicitIndex = volumeIndex?.takeIf { it.isFinite() && it > 0 }
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
data class ReadingUnitContent(
    val id: String,
    val title: String,
    val progressPercent: Int? = null,
    val positionLabel: String? = null,
    val href: String? = null,
    val sortOrder: Int = 0,
    val readingState: ChapterReadingState = ChapterReadingState.Unread,
)

@Serializable
enum class ChapterReadingState { Current, Read, Unread }

@Immutable
@Serializable
data class MediaContent(
    val kind: String,
    val volumes: List<VolumeContent>,
)

@Immutable
@Serializable
data class WorkDetailContent(
    val work: WorkCard,
    val seriesId: String?,
    val seriesName: String?,
    val authorFacetId: String?,
    val description: String?,
    val tags: List<String>,
    val media: List<MediaContent>,
    val selectedMediaKind: String?,
    val completed: Boolean = false,
    val readingUnits: List<ReadingUnitContent> = emptyList(),
) {
    val hasDescription: Boolean get() = !description.isNullOrBlank()

    val showsMediaPicker: Boolean get() = media.map { it.kind.uppercase() }.distinct().size > 1

    fun usesEbookChapterFallback(selectedMediaKind: String?): Boolean =
        selectedMediaKind.equals("EBOOK", ignoreCase = true) &&
            media.firstOrNull { it.kind.equals("EBOOK", ignoreCase = true) }?.volumes?.size == 1 &&
            readingUnits.isNotEmpty()
}
