package com.ermao.library.features.reader.infrastructure

import com.ermao.library.archive.infrastructure.ArchiveCore
import com.ermao.library.archive.infrastructure.ArchiveCorePage
import com.ermao.library.shared.modules.reader.ReaderComicPage
import java.io.File
import java.util.Locale
import org.readium.r2.shared.publication.Layout
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.LocalizedString
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.ReadingProgression
import org.readium.r2.shared.publication.services.PerResourcePositionsService
import org.readium.r2.shared.util.AbsoluteUrl
import org.readium.r2.shared.util.Try
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.mediatype.MediaType
import org.readium.r2.shared.util.resource.Resource

/** Opens original ZIP/RAR/RAR5 comics through the bounded native archive core. */
internal class CbzReadiumPublicationFactory {
    fun indexPages(file: File, pageHints: List<ReaderComicPage> = emptyList()): List<ReaderComicPage> =
        ArchiveCore.open(file).use { archive -> indexPages(archive, pageHints) }

    fun open(file: File, title: String, pageHints: List<ReaderComicPage>): Publication {
        val archive = ArchiveCore.open(file)
        try {
            val localPages = indexPages(archive, pageHints)
            val resources = archive.pages.associate { page ->
                requireNotNull(Url("pages/${page.index}")) to ArchivePageResource(archive, page)
            }
            val readingOrder = localPages.mapIndexed { index, page ->
                Link(
                    href = requireNotNull(Url(page.resourceHref)),
                    mediaType = requireNotNull(MediaType(page.mediaType)),
                    title = page.title,
                    rels = if (index == 0) setOf("cover") else emptySet(),
                )
            }
            return Publication(
                manifest = Manifest(
                    metadata = Metadata(
                        identifier = "urn:shuku:comic:${file.nameWithoutExtension}",
                        type = "https://schema.org/ComicStory",
                        conformsTo = setOf(Publication.Profile.DIVINA),
                        localizedTitle = LocalizedString(title),
                        readingProgression = ReadingProgression.LTR,
                        layout = Layout.FIXED,
                    ),
                    readingOrder = readingOrder,
                    tableOfContents = readingOrder,
                ),
                container = ArchivePageContainer(archive, resources),
                servicesBuilder = Publication.ServicesBuilder(
                    positions = PerResourcePositionsService.createFactory(
                        fallbackMediaType = requireNotNull(MediaType("image/*")),
                    ),
                ),
            )
        } catch (error: Throwable) {
            archive.close()
            throw error
        }
    }

    private fun indexPages(
        archive: ArchiveCore,
        pageHints: List<ReaderComicPage>,
    ): List<ReaderComicPage> = archive.pages.map { page ->
        val mediaType = when (page.path.substringAfterLast('.').lowercase(Locale.ROOT)) {
            "jpg", "jpeg" -> "image/jpeg"
            "png" -> "image/png"
            "gif" -> "image/gif"
            "webp" -> "image/webp"
            else -> "image/*"
        }
        ReaderComicPage(
            pageIndex = page.index,
            resourceHref = "pages/${page.index}",
            mediaType = mediaType,
            title = pageHints.getOrNull(page.index)?.title ?: page.path.substringAfterLast('/'),
        )
    }

}

private class ArchivePageResource(
    private val archive: ArchiveCore,
    private val page: ArchiveCorePage,
) : Resource {
    override val sourceUrl: AbsoluteUrl? = null

    override suspend fun properties(): Try<Resource.Properties, ReadError> = Try.success(Resource.Properties())

    override suspend fun length(): Try<Long, ReadError> = Try.success(page.sizeBytes)

    override suspend fun read(range: LongRange?): Try<ByteArray, ReadError> = try {
        val bytes = archive.readPage(page.index)
        val start = (range?.first ?: 0L).coerceAtLeast(0L)
        if (range?.isEmpty() == true || start >= bytes.size) {
            Try.success(byteArrayOf())
        } else {
            val endExclusive = ((range?.last ?: bytes.lastIndex.toLong()) + 1L)
                .coerceAtMost(bytes.size.toLong())
            Try.success(bytes.copyOfRange(start.toInt(), endExclusive.toInt()))
        }
    } catch (error: OutOfMemoryError) {
        Try.failure(ReadError.OutOfMemory(error))
    } catch (error: Exception) {
        Try.failure(ReadError.Decoding(error))
    }

    override fun close() = Unit
}

private class ArchivePageContainer(
    private val archive: ArchiveCore,
    private val resources: Map<Url, Resource>,
) : Container<Resource> {
    override val sourceUrl: AbsoluteUrl? = null
    override val entries: Set<Url> = resources.keys
    override fun get(url: Url): Resource? = resources[url]

    override fun close() {
        resources.values.forEach(Resource::close)
        archive.close()
    }
}

/** Compatibility helper for persisted pre-v4 comic href diagnostics. */
internal fun encodeComicArchiveEntryHref(name: String): String = buildString {
    name.encodeToByteArray().forEach { byte ->
        val value = byte.toInt() and 0xFF
        val character = value.toChar()
        if ((character.isLetterOrDigit() && value < 128) || character in "-._~/") {
            append(character)
        } else {
            append('%')
            append(value.toString(16).uppercase(Locale.ROOT).padStart(2, '0'))
        }
    }
}
