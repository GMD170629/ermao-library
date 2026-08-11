package com.ermao.library.shared.modules.library.domain

data class WorkSummary(
    val id: String,
    val title: String,
    val author: String,
    val coverUrl: String,
    val availableMediaKinds: List<MediaKind>,
    val progress: Double,
)

data class WorkDetailSummary(
    val id: String,
    val title: String,
    val author: String,
    val description: String?,
    val tags: List<String>,
    val seriesName: String?,
    val seriesIndex: Double?,
    val coverStatus: String,
    val coverUrl: String,
    val recentMediaKind: MediaKind?,
    val continueVolumeId: String?,
    val completed: Boolean,
    val mediaVersions: List<MediaVersion>,
    val availableMediaKinds: List<MediaKind>,
    val detailTabs: List<WorkDetailTab>,
    val selectedDetailTab: String,
)

@JvmInline
value class MediaKind(val wireValue: String) {
    companion object {
        val Ebook = MediaKind("EBOOK")
        val Comic = MediaKind("COMIC")
        val Audiobook = MediaKind("AUDIOBOOK")
    }
}

data class WorkDetailTab(
    val key: String,
    val label: String,
    val sortOrder: Int,
)
