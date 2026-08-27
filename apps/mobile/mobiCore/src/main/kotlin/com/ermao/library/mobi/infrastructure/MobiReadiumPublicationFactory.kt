package com.ermao.library.mobi.infrastructure

import org.readium.r2.streamer.parser.epub.EpubPositionsService

import java.io.File
import java.io.IOException
import org.readium.r2.shared.InternalReadiumApi
import org.readium.r2.shared.publication.Contributor
import org.readium.r2.shared.publication.Layout
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.LocalizedString
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.ReadingProgression
import org.readium.r2.shared.util.AbsoluteUrl
import org.readium.r2.shared.util.Try
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.CompositeContainer
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.mediatype.MediaType
import org.readium.r2.shared.util.resource.Resource
import org.readium.r2.shared.util.resource.SingleResourceContainer

const val MOBI_PUBLICATION_NORMALIZATION_IDENTIFIER =
    "ermao-mobi-core-v1+shuku-locator-dom-v2"

/**
 * Creates a Readium reflowable Publication backed by one live `MobiCoreBook`.
 *
 * Opening only reads the ABI metadata and resource descriptors. Publication bytes stay in the
 * native core and are copied on demand in chunks no larger than [MOBI_CORE_MAX_READ_BYTES]. The
 * adapter never creates an EPUB, an unpacked directory, or a second whole-publication byte cache.
 */
@OptIn(InternalReadiumApi::class)
class MobiReadiumPublicationFactory {
    fun open(
        file: File,
        transformContainer: (Container<Resource>) -> Container<Resource> = { it },
    ): MobiReadiumPublication {
        val book = try {
            MobiCoreBook.open(file)
        } catch (error: Throwable) {
            throw error.toPublicationOpenException()
        }
        try {
            val info = book.info()
            require(info.readingOrderCount > 0) { "MOBI reading order is empty" }
            val descriptors = List(info.resourceCount) { index ->
                val resource = book.resource(index)
                MobiResourceDescriptor(
                    index = index,
                    href = exactVirtualHref(resource.sourceName),
                    mediaType = requireNotNull(MediaType(resource.mediaType)) {
                        "Unsupported MOBI resource media type: ${resource.mediaType}"
                    },
                    decodedLength = resource.decodedLength,
                ).also { descriptor ->
                    require(descriptor.decodedLength in 0..MAXIMUM_RESOURCE_BYTES) {
                        "MOBI resource exceeds the runtime limit"
                    }
                }
            }
            require(descriptors.map(MobiResourceDescriptor::href).toSet().size == descriptors.size) {
                "MOBI virtual HREFs are not unique"
            }

            val readingIndices = List(info.readingOrderCount, book::readingOrderResourceIndex)
            require(readingIndices.all(descriptors.indices::contains)) {
                "MOBI reading order references an unknown resource"
            }
            require(readingIndices.toSet().size == readingIndices.size) {
                "MOBI reading order contains a duplicate resource"
            }
            require(readingIndices.all { descriptors[it].mediaType in REFLOWABLE_MEDIA_TYPES }) {
                "MOBI reading order contains a non-reflowable resource"
            }
            info.coverResourceIndex?.let { coverIndex ->
                require(coverIndex in descriptors.indices) { "MOBI cover references an unknown resource" }
            }

            val resources = descriptors.map { descriptor ->
                MobiLazyResource(book, descriptor)
            }
            val resourceByIndex = resources.associateBy { it.descriptor.index }
            val readingIndexSet = readingIndices.toSet()
            val readingOrder = readingIndices.map { index ->
                resourceByIndex.getValue(index).link(
                    rels = if (index == info.coverResourceIndex) setOf(COVER_REL) else emptySet(),
                )
            }
            val manifestResources = resources
                .filterNot { it.descriptor.index in readingIndexSet }
                .map { resource ->
                    resource.link(
                        rels = if (resource.descriptor.index == info.coverResourceIndex) {
                            setOf(COVER_REL)
                        } else {
                            emptySet()
                        },
                    )
                }
            val tableOfContents = buildTableOfContents(book, info.tocCount, resourceByIndex)
            val container = MobiPublicationContainer(book, resources)
            val publication = Publication(
                manifest = Manifest(
                    metadata = metadata(book, info, file),
                    readingOrder = readingOrder,
                    resources = manifestResources,
                    tableOfContents = tableOfContents,
                ),
                container = transformContainer(container),
                servicesBuilder = Publication.ServicesBuilder(
                    // Use parser descriptor lengths, never the security-decorated resources:
                    // asking a TransformingResource for its length reads the entire body.
                    positions = {
                        EpubPositionsService(
                            readingOrder,
                            Layout.REFLOWABLE,
                            container,
                            EpubPositionsService.ReflowableStrategy.ArchiveEntryLength(1024),
                        )
                    },
                ),
            )
            return MobiReadiumPublication(
                publication = publication,
                parser = MobiCoreBook.parserIdentifier,
                normalization = MOBI_PUBLICATION_NORMALIZATION_IDENTIFIER,
                resources = resources.map(::MobiResourceEvidence),
                readingOrderHrefs = readingOrder.map { it.href.toString() },
            )
        } catch (error: Throwable) {
            book.close()
            throw error.toPublicationOpenException()
        }
    }

    private fun metadata(
        book: MobiCoreBook,
        info: MobiCoreBookInfo,
        file: File,
    ): Metadata {
        val title = book.metadata(MobiCoreMetadataField.Title)?.takeIf(String::isNotBlank)
            ?: file.nameWithoutExtension
        val author = book.metadata(MobiCoreMetadataField.Author)?.takeIf(String::isNotBlank)
        val publisher = book.metadata(MobiCoreMetadataField.Publisher)?.takeIf(String::isNotBlank)
        return Metadata(
            identifier = "urn:shuku:mobi:${file.name}",
            type = "https://schema.org/Book",
            conformsTo = setOf(Publication.Profile.EPUB),
            localizedTitle = LocalizedString(title),
            languages = listOfNotNull(
                book.metadata(MobiCoreMetadataField.Language)?.takeIf(String::isNotBlank),
            ),
            authors = listOfNotNull(author?.let(::Contributor)),
            publishers = listOfNotNull(publisher?.let(::Contributor)),
            readingProgression = when (info.readingDirection) {
                MobiCoreReadingDirection.RightToLeft -> ReadingProgression.RTL
                MobiCoreReadingDirection.LeftToRight,
                MobiCoreReadingDirection.Unknown,
                -> ReadingProgression.LTR
            },
            description = book.metadata(MobiCoreMetadataField.Description)?.takeIf(String::isNotBlank),
            layout = Layout.REFLOWABLE,
        )
    }

    private fun buildTableOfContents(
        book: MobiCoreBook,
        tocCount: Int,
        resourcesByIndex: Map<Int, MobiLazyResource>,
    ): List<Link> {
        val entries = List(tocCount, book::toc)
        entries.forEachIndexed { index, entry ->
            require(entry.parentIndex == null || entry.parentIndex in 0 until index) {
                "MOBI TOC parent must precede its child"
            }
            require(entry.targetResourceIndex == null || entry.targetResourceIndex in resourcesByIndex) {
                "MOBI TOC references an unknown resource"
            }
        }
        val children = entries.indices.groupBy { entries[it].parentIndex }

        fun build(index: Int): Link? {
            val entry = entries[index]
            val target = entry.targetResourceIndex?.let(resourcesByIndex::get) ?: return null
            val href = requireNotNull(Url(target.descriptor.href)).let { resourceUrl ->
                entry.fragment
                    ?.takeIf(String::isNotBlank)
                    ?.also { fragment ->
                        require(fragment.length <= MAXIMUM_FRAGMENT_LENGTH && fragment.none(Char::isISOControl)) {
                            "MOBI TOC contains an unsafe fragment"
                        }
                    }
                    ?.let(resourceUrl::addFragment)
                    ?: resourceUrl
            }
            return Link(
                href = href,
                mediaType = target.descriptor.mediaType,
                title = entry.title?.takeIf(String::isNotBlank) ?: target.descriptor.href,
                children = children[index].orEmpty().mapNotNull(::build),
            )
        }

        return children[null].orEmpty().mapNotNull(::build)
    }

    private fun exactVirtualHref(value: String): String {
        require(value.isNotBlank() && value == value.trim() && value.length <= MAXIMUM_HREF_LENGTH) {
            "libmobi produced an empty virtual HREF"
        }
        val normalized = value.lowercase()
        require(
            !value.startsWith('/') &&
                '\\' !in value &&
                '?' !in value &&
                '#' !in value &&
                ':' !in value &&
                value.none(Char::isISOControl) &&
                "%2e" !in normalized &&
                "%2f" !in normalized &&
                "%5c" !in normalized &&
                value.split('/').none { it.isBlank() || it == "." || it == ".." } &&
                Url(value) != null
        ) {
            "libmobi produced an unsafe virtual HREF"
        }
        return value
    }

    private companion object {
        const val COVER_REL = "cover"
        const val MAXIMUM_FRAGMENT_LENGTH = 2_048
        const val MAXIMUM_HREF_LENGTH = 4_096
        const val MAXIMUM_RESOURCE_BYTES = 64L * 1024L * 1024L
        val REFLOWABLE_MEDIA_TYPES = setOf(MediaType.XHTML, MediaType.HTML)
    }
}

enum class MobiPublicationErrorKind {
    DrmProtected,
    Unsupported,
    Corrupt,
    LimitExceeded,
    OutOfMemory,
    Io,
}

/** Stable product-facing failure; native status text and paths are intentionally not exposed. */
class MobiPublicationOpenException(
    val kind: MobiPublicationErrorKind,
    cause: Throwable,
) : Exception("Unable to open MOBI publication: ${kind.name}", cause)

class MobiReadiumPublication internal constructor(
    val publication: Publication,
    val parser: String,
    val normalization: String,
    val resources: List<MobiResourceEvidence>,
    val readingOrderHrefs: List<String>,
) : AutoCloseable {
    /** Test and diagnostic access only. Bytes are read on demand and are never retained. */
    fun decodedText(href: String): String? = resources
        .firstOrNull { it.href == href }
        ?.readBytes()
        ?.toString(Charsets.UTF_8)

    override fun close() = publication.close()
}

/** Immutable descriptor evidence. Bytes are read only when a diagnostic explicitly asks for them. */
class MobiResourceEvidence internal constructor(
    private val resource: MobiLazyResource,
) {
    val href: String = resource.descriptor.href
    val mediaType: String = resource.descriptor.mediaType.toString()
    val byteCount: Long = resource.descriptor.decodedLength
    internal fun readBytes(): ByteArray = resource.readExact(null)
}

internal data class MobiResourceDescriptor(
    val index: Int,
    val href: String,
    val mediaType: MediaType,
    val decodedLength: Long,
)

internal class MobiLazyResource(
    private val book: MobiCoreBook,
    val descriptor: MobiResourceDescriptor,
) : Resource {
    override val sourceUrl: AbsoluteUrl? = null

    override suspend fun properties(): Try<Resource.Properties, ReadError> =
        Try.success(Resource.Properties())

    override suspend fun length(): Try<Long, ReadError> = Try.success(descriptor.decodedLength)

    override suspend fun read(range: LongRange?): Try<ByteArray, ReadError> = try {
        Try.success(readExact(range))
    } catch (error: OutOfMemoryError) {
        Try.failure(ReadError.OutOfMemory(error))
    } catch (error: Exception) {
        Try.failure(ReadError.Decoding(error))
    }

    internal fun readExact(range: LongRange?): ByteArray {
        val start = range?.first?.coerceAtLeast(0L) ?: 0L
        if (start >= descriptor.decodedLength || range?.isEmpty() == true) return byteArrayOf()
        val requestedEnd = range?.last ?: (descriptor.decodedLength - 1L)
        val endInclusive = requestedEnd.coerceAtMost(descriptor.decodedLength - 1L)
        if (endInclusive < start) return byteArrayOf()
        val byteCount = endInclusive - start + 1L
        require(byteCount <= Int.MAX_VALUE.toLong()) { "MOBI resource range is too large" }

        val output = ByteArray(byteCount.toInt())
        var written = 0
        while (written < output.size) {
            val bytes = book.readResource(
                resourceIndex = descriptor.index,
                offset = start + written,
                length = minOf(MOBI_CORE_MAX_READ_BYTES, output.size - written),
            )
            check(bytes.isNotEmpty()) { "MOBI resource ended before its declared length" }
            check(bytes.size <= output.size - written) { "MOBI resource exceeded the requested range" }
            bytes.copyInto(output, written)
            written += bytes.size
        }
        return output
    }

    fun link(rels: Set<String> = emptySet()): Link = Link(
        href = requireNotNull(Url(descriptor.href)),
        mediaType = descriptor.mediaType,
        rels = rels,
    )

    // The publication container owns the shared book handle, not individual resources.
    override fun close() = Unit
}

private class MobiPublicationContainer(
    private val book: MobiCoreBook,
    resources: List<MobiLazyResource>,
) : Container<Resource> {
    private val delegate = CompositeContainer(
        resources.map { resource ->
            SingleResourceContainer(requireNotNull(Url(resource.descriptor.href)), resource)
        },
    )

    override val sourceUrl: AbsoluteUrl?
        get() = delegate.sourceUrl

    override val entries: Set<Url>
        get() = delegate.entries

    override fun get(url: Url): Resource? = delegate[url]

    override fun close() {
        try {
            delegate.close()
        } finally {
            book.close()
        }
    }
}

private fun ByteArray.hex(): String = joinToString("") { "%02x".format(it.toInt() and 0xff) }

private fun Throwable.toPublicationOpenException(): MobiPublicationOpenException {
    if (this is MobiPublicationOpenException) return this
    val kind = when (this) {
        is OutOfMemoryError -> MobiPublicationErrorKind.OutOfMemory
        is IOException -> MobiPublicationErrorKind.Io
        is MobiCoreException -> when (status) {
            MobiCoreStatus.DrmProtected -> MobiPublicationErrorKind.DrmProtected
            MobiCoreStatus.Unsupported -> MobiPublicationErrorKind.Unsupported
            MobiCoreStatus.LimitExceeded -> MobiPublicationErrorKind.LimitExceeded
            MobiCoreStatus.OutOfMemory -> MobiPublicationErrorKind.OutOfMemory
            MobiCoreStatus.FileNotFound,
            MobiCoreStatus.Io,
            -> MobiPublicationErrorKind.Io
            MobiCoreStatus.InvalidArgument,
            MobiCoreStatus.Corrupt,
            MobiCoreStatus.ParseFailed,
            MobiCoreStatus.NoContent,
            MobiCoreStatus.NotFound,
            MobiCoreStatus.OutOfRange,
            MobiCoreStatus.BufferTooSmall,
            MobiCoreStatus.Internal,
            -> MobiPublicationErrorKind.Corrupt
        }
        else -> MobiPublicationErrorKind.Corrupt
    }
    return MobiPublicationOpenException(kind, this)
}
