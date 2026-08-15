@file:OptIn(org.readium.r2.shared.ExperimentalReadiumApi::class)

package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderPdfPage
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.LocalizedString
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.services.PositionsService
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.mediatype.MediaType

internal fun createShukuPdfPublication(
    identifier: String,
    title: String,
    pages: List<ReaderPdfPage>,
): Publication {
    val positionSpecs = createCanonicalPdfPositionSpecs(pages)
    val href = Url("publication.pdf")!!
    val manifest = Manifest(
        metadata = Metadata(
            identifier = identifier,
            conformsTo = setOf(Publication.Profile.PDF),
            localizedTitle = LocalizedString(title),
            numberOfPages = pages.size,
        ),
        readingOrder = listOf(Link(href = href, mediaType = MediaType.PDF, title = title)),
        tableOfContents = pages.map { page ->
            Link(
                href = Url("publication.pdf#page=${page.pageIndex + 1}")!!,
                mediaType = MediaType.PDF,
                title = page.title,
            )
        },
    )
    return Publication(
        manifest = manifest,
        servicesBuilder = Publication.ServicesBuilder(
            positions = { CanonicalPdfPositionsService(href, positionSpecs) },
        ),
    )
}

internal data class CanonicalPdfPositionSpec(
    val position: Int,
    val totalProgression: Double,
)

internal fun createCanonicalPdfPositionSpecs(pages: List<ReaderPdfPage>): List<CanonicalPdfPositionSpec> {
    require(pages.isNotEmpty() && pages.map(ReaderPdfPage::pageIndex) == pages.indices.toList())
    return pages.map { page ->
        CanonicalPdfPositionSpec(
            position = page.pageIndex + 1,
            totalProgression = if (pages.size == 1) 0.0 else {
                page.pageIndex.toDouble() / (pages.size - 1)
            },
        )
    }
}

private class CanonicalPdfPositionsService(
    private val href: Url,
    private val positions: List<CanonicalPdfPositionSpec>,
) : PositionsService {
    override suspend fun positionsByReadingOrder(): List<List<Locator>> = listOf(
        positions.map { position ->
            Locator(
                href = href,
                mediaType = MediaType.PDF,
                locations = Locator.Locations(
                    position = position.position,
                    totalProgression = position.totalProgression,
                ),
            )
        },
    )
}
