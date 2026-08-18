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
    val lastReadAtEpochMillis: Long?,
    val resumeVolumeId: String? = null,
)

@Immutable
@Serializable
data class HomeContent(
    val continueReading: ContinueReadingCard?,
    val recentReading: List<WorkCard>,
    val recentAdded: List<WorkCard>,
)

@Serializable
enum class ContentFreshness { Fresh, Stale }

@Immutable
@Serializable
data class VolumeContent(
    val id: String,
    val title: String,
    val format: String,
    val readerType: String = "reflowable",
    val versionId: String = "",
    val volumeIndex: Double? = null,
    val sortOrder: Int = 0,
    val publisher: String? = null,
    val publishedAt: String? = null,
    val language: String? = null,
    val isbn: String? = null,
    val identifier: String? = null,
    val narrator: String? = null,
    val pageCount: Int? = null,
    val metadataSource: String? = null,
    val suggestedMediaKind: String? = null,
    val kindleSendAvailable: Boolean = false,
    val files: List<VolumeFileContent> = emptyList(),
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
data class VolumeFileContent(
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
data class VersionContent(
    val id: String,
    val sourceKey: String,
    val sourceName: String? = null,
    val volumes: List<VolumeContent>,
    val volumeCount: Int = volumes.size,
)

@Immutable
@Serializable
data class WorkDetailContent(
    val work: WorkCard,
    val seriesId: String?,
    val seriesName: String?,
    val seriesIndex: Double? = null,
    val authorFacetId: String?,
    val description: String?,
    val tags: List<String>,
    val versions: List<VersionContent>,
    val selectedVersionId: String?,
    val completed: Boolean = false,
    val readingUnits: List<ReadingUnitContent> = emptyList(),
) {
    val hasDescription: Boolean get() = !description.isNullOrBlank()

    val showsVersionPicker: Boolean get() = versions.size > 1

    val allVolumes: List<VolumeContent> get() = versions.flatMap { it.volumes }

    fun supportsChapterDirectory(volumeId: String?): Boolean =
        volumeId != null &&
            allVolumes.firstOrNull { it.id == volumeId }
                ?.readerType.equals("reflowable", ignoreCase = true) &&
            readingUnits.isNotEmpty()
}
