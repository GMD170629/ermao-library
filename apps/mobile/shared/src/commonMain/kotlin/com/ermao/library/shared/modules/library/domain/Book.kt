package com.ermao.library.shared.modules.library.domain

data class BookSummary(
    val id: String,
    val title: String,
    val author: String?,
    val coverUrl: String,
    val progress: Double,
)

data class BookDetailSummary(
    val id: String,
    val sourceNodeId: String,
    val title: String,
    val author: String?,
    val description: String?,
    val tags: List<String>,
    val seriesName: String?,
    val seriesFacet: AppliedFacet? = null,
    val authorFacets: List<AppliedFacet> = emptyList(),
    val seriesIndex: Double?,
    val coverStatus: String,
    val coverUrl: String,
    val continueResourceId: String?,
    val continueResourceProgress: Double,
    val completed: Boolean,
    val resources: List<Resource>,
)

data class AppliedFacet(
    val id: String,
    val kind: FacetKind,
    val name: String,
)

enum class FacetKind { Series, Author, Tag }
