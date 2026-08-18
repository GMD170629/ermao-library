package com.ermao.library.shared.modules.library.domain

import kotlin.jvm.JvmInline

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
    val seriesFacet: AppliedFacet? = null,
    val authorFacets: List<AppliedFacet> = emptyList(),
    val seriesIndex: Double?,
    val coverStatus: String,
    val coverUrl: String,
    val continueVolumeId: String?,
    val continueVolumeProgress: Double,
    val completed: Boolean,
    val versions: List<WorkVersion>,
)

data class AppliedFacet(
    val id: String,
    val kind: FacetKind,
    val name: String,
)

enum class FacetKind { Series, Author }

@JvmInline
value class MediaKind(val wireValue: String) {
    companion object {
        val Ebook = MediaKind("EBOOK")
        val Comic = MediaKind("COMIC")
        val Audiobook = MediaKind("AUDIOBOOK")
    }
}
