package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.application.ComicPageReadResult
import com.ermao.library.shared.modules.reader.application.ComicPageServerPort
import com.ermao.library.shared.modules.reader.ReaderComicImageVariant
import com.ermao.library.shared.modules.reader.RemoteComicReaderSource
import org.readium.r2.shared.publication.Layout
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.LocalizedString
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.ReadingProgression
import org.readium.r2.shared.publication.services.PerResourcePositionsService
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.mediatype.MediaType
import org.readium.r2.shared.util.resource.FailureResource
import org.readium.r2.shared.util.resource.InMemoryResource
import org.readium.r2.shared.util.resource.LazyResource
import org.readium.r2.shared.util.resource.Resource

/** Readium image publication whose resources are fetched one page at a time from Reader V4. */
internal class RemoteComicReadiumPublicationFactory(
    private val server: ComicPageServerPort,
    private val onFailure: (com.ermao.library.shared.modules.reader.ReaderError) -> Unit,
) {
    fun open(
        source: RemoteComicReaderSource,
        imageVariant: ReaderComicImageVariant,
    ): Publication {
        val pagesByHref = source.pages.associateBy { it.resourceHref }
        val entries = pagesByHref.keys.map { requireNotNull(Url(it)) }.toSet()
        val container = object : Container<Resource> {
            override val entries: Set<Url> = entries

            override fun get(url: Url): Resource {
                val page = pagesByHref[url.toString()]
                    ?: return FailureResource(ReadError.Decoding(IllegalArgumentException("COMIC_PAGE_OUT_OF_RANGE")))
                return LazyResource {
                    when (val result = server.read(source, page.pageIndex, imageVariant)) {
                        is ComicPageReadResult.Content -> InMemoryResource(result.bytes)
                        is ComicPageReadResult.Failure -> {
                            onFailure(result.readerError)
                            FailureResource(ReadError.Decoding(ReaderOpenFailure(result.readerError)))
                        }
                    }
                }
            }

            override fun close() = Unit
        }
        val readingOrder = source.pages.mapIndexed { index, page ->
            Link(
                href = requireNotNull(Url(page.resourceHref)),
                mediaType = requireNotNull(MediaType(page.mediaType)),
                title = (page.pageIndex + 1).toString(),
                rels = if (index == 0) setOf("cover") else emptySet(),
            )
        }
        return Publication(
            manifest = Manifest(
                metadata = Metadata(
                    identifier = "urn:shuku:comic:${source.resourceId}",
                    type = "https://schema.org/ComicStory",
                    conformsTo = setOf(Publication.Profile.DIVINA),
                    localizedTitle = LocalizedString(source.displayTitle),
                    readingProgression = ReadingProgression.LTR,
                    layout = Layout.FIXED,
                ),
                readingOrder = readingOrder,
                tableOfContents = readingOrder,
            ),
            container = container,
            servicesBuilder = Publication.ServicesBuilder(
                positions = PerResourcePositionsService.createFactory(
                    fallbackMediaType = requireNotNull(MediaType("image/*")),
                ),
            ),
        )
    }
}
