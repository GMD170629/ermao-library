package com.ermao.library.features.reader.infrastructure

import org.readium.r2.streamer.parser.epub.EpubPositionsService

import com.ermao.library.shared.modules.reader.Fb2NavigationEntry
import java.io.File
import org.readium.r2.shared.publication.Layout
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.LocalizedString
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.ReadingProgression
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.CompositeContainer
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.mediatype.MediaType
import org.readium.r2.shared.util.resource.InMemoryResource
import org.readium.r2.shared.util.resource.Resource
import org.readium.r2.shared.util.resource.SingleResourceContainer

internal class Fb2ReadiumPublicationFactory {
    fun open(file: File, fallbackTitle: String): Publication {
        val parsed = Fb2SourceParser.read(file, fallbackTitle)
        val document = parsed.document
        val containers: List<Container<Resource>> = document.resources.map { resource ->
            SingleResourceContainer(
                requireNotNull(Url(resource.href)),
                InMemoryResource(EpubContentSecurityPolicy.generatedChapter(resource.xhtml)),
            )
        } + listOf(SingleResourceContainer(
            requireNotNull(Url(document.stylesheetHref)),
            InMemoryResource(document.stylesheet.toByteArray()),
        )) + parsed.images.map { (href, bytes) ->
            SingleResourceContainer(requireNotNull(Url(href)), InMemoryResource(bytes))
        }
        return Publication(
            manifest = Manifest(
                metadata = Metadata(
                    identifier = "urn:shuku:fb2:${file.nameWithoutExtension}",
                    type = "https://schema.org/Book",
                    conformsTo = setOf(Publication.Profile.EPUB),
                    localizedTitle = LocalizedString(document.title),
                    languages = listOfNotNull(document.language),
                    readingProgression = ReadingProgression.LTR,
                    layout = Layout.REFLOWABLE,
                ),
                readingOrder = document.resources.map { resource ->
                    Link(href = requireNotNull(Url(resource.href)), mediaType = MediaType.XHTML, title = resource.title)
                },
                resources = listOf(Link(href = requireNotNull(Url(document.stylesheetHref)), mediaType = MediaType.CSS)) +
                    document.images.map { Link(href = requireNotNull(Url(it.href)), mediaType = MediaType(it.mediaType)) },
                tableOfContents = document.tableOfContents.map(::navigationLink),
            ),
            container = CompositeContainer(containers),
            servicesBuilder = Publication.ServicesBuilder(
                positions = EpubPositionsService.createFactory(),
            ),
        )
    }

    private fun navigationLink(entry: Fb2NavigationEntry): Link = Link(
        href = requireNotNull(Url(entry.href)),
        mediaType = MediaType.XHTML,
        title = entry.title,
        children = entry.children.map(::navigationLink),
    )
}
