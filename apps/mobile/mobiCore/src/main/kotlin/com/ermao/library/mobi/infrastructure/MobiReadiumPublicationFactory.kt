package com.ermao.library.mobi.infrastructure

import java.io.File
import java.security.MessageDigest
import org.readium.r2.shared.InternalReadiumApi
import org.readium.r2.shared.publication.Layout
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.LocalizedString
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.CompositeContainer
import org.readium.r2.shared.util.mediatype.MediaType
import org.readium.r2.shared.util.resource.InMemoryResource
import org.readium.r2.shared.util.resource.SingleResourceContainer

/**
 * Builds the Android in-memory Readium Publication directly from the pinned
 * `ermao_mobi_*` ABI. The XHTML bytes and virtual HREFs are not rewritten in
 * Kotlin, keeping this path conformant with the Web and iOS adapters.
 */
@OptIn(InternalReadiumApi::class)
class MobiReadiumPublicationFactory {
    fun open(file: File): MobiReadiumPublication {
        val originalHash = sha256(file)
        return MobiCoreBook.open(file).use { book ->
            val info = book.info()
            require(info.readingOrderCount > 0) { "MOBI reading order is empty" }
            val resources = List(info.resourceCount) { index ->
                val descriptor = book.resource(index)
                val href = exactVirtualHref(descriptor.sourceName)
                val bytes = readFully(book, index, descriptor.decodedLength)
                MobiPublicationResource(
                    index = index,
                    href = href,
                    mediaType = requireNotNull(MediaType(descriptor.mediaType)) {
                        "Unsupported MOBI resource media type: ${descriptor.mediaType}"
                    },
                    bytes = bytes,
                    sha256 = sha256(bytes),
                )
            }
            require(resources.map(MobiPublicationResource::href).toSet().size == resources.size) {
                "MOBI virtual HREFs are not unique"
            }
            val readingIndices = List(info.readingOrderCount, book::readingOrderResourceIndex)
            val readingIndexSet = readingIndices.toSet()
            val readingOrder = readingIndices.map { resources[it].link() }
            val manifestResources = resources.filterNot { it.index in readingIndexSet }.map { it.link() }
            val container = CompositeContainer(
                resources.map { resource ->
                    val url = requireNotNull(Url(resource.href))
                    SingleResourceContainer(url, InMemoryResource(resource.bytes))
                },
            )
            val title = book.metadata(MobiCoreMetadataField.Title)?.takeIf(String::isNotBlank)
                ?: file.nameWithoutExtension
            val language = book.metadata(MobiCoreMetadataField.Language)?.takeIf(String::isNotBlank)
            val publication = Publication(
                manifest = Manifest(
                    metadata = Metadata(
                        identifier = "urn:shuku:mobi:$originalHash",
                        conformsTo = setOf(Publication.Profile.EPUB),
                        localizedTitle = LocalizedString(title),
                        languages = listOfNotNull(language),
                        layout = Layout.REFLOWABLE,
                    ),
                    readingOrder = readingOrder,
                    resources = manifestResources,
                ),
                container = container,
            )
            MobiReadiumPublication(
                publication = publication,
                originalFileHash = originalHash,
                parser = MobiCoreBook.parserIdentifier,
                normalization = MobiCoreBook.normalizationIdentifier,
                resources = resources.map { it.evidence() },
                readingOrderHrefs = readingOrder.map { it.href.toString() },
                decodedResources = resources.associate { it.href to it.bytes },
            )
        }
    }

    private fun readFully(book: MobiCoreBook, index: Int, length: Long): ByteArray {
        require(length in 0..MAXIMUM_RESOURCE_BYTES) { "MOBI resource exceeds POC limit" }
        val output = ByteArray(length.toInt())
        var offset = 0
        while (offset < output.size) {
            val chunk = book.readResource(
                resourceIndex = index,
                offset = offset.toLong(),
                length = minOf(MOBI_CORE_MAX_READ_BYTES, output.size - offset),
            )
            check(chunk.isNotEmpty()) { "MOBI resource ended before its declared length" }
            chunk.copyInto(output, offset)
            offset += chunk.size
        }
        return output
    }

    private fun exactVirtualHref(value: String): String {
        require(value.isNotBlank() && !value.startsWith('/') && '\\' !in value) {
            "libmobi produced an unsafe virtual HREF"
        }
        require('?' !in value && '#' !in value && value.split('/').none { it.isBlank() || it == "." || it == ".." }) {
            "libmobi produced a non-canonical virtual HREF"
        }
        return value
    }

    private fun MobiPublicationResource.link(): Link = Link(
        href = requireNotNull(Url(href)),
        mediaType = mediaType,
    )

    private fun sha256(file: File): String = file.inputStream().use { input ->
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            digest.update(buffer, 0, count)
        }
        digest.digest().hex()
    }

    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes)
        .hex()

    private fun ByteArray.hex(): String = joinToString("") { "%02x".format(it.toInt() and 0xff) }

    private companion object {
        const val MAXIMUM_RESOURCE_BYTES = 64L * 1024L * 1024L
    }
}

class MobiReadiumPublication internal constructor(
    val publication: Publication,
    /** Lower-case SHA-256 without a prefix, matching Reader v4 canonical wire output. */
    val originalFileHash: String,
    val parser: String,
    val normalization: String,
    val resources: List<MobiResourceEvidence>,
    val readingOrderHrefs: List<String>,
    private val decodedResources: Map<String, ByteArray>,
) : AutoCloseable {
    fun decodedText(href: String): String? = decodedResources[href]?.toString(Charsets.UTF_8)

    override fun close() = publication.close()
}

data class MobiResourceEvidence(
    val href: String,
    val mediaType: String,
    val byteCount: Int,
    val sha256: String,
)

private data class MobiPublicationResource(
    val index: Int,
    val href: String,
    val mediaType: MediaType,
    val bytes: ByteArray,
    val sha256: String,
) {
    fun evidence(): MobiResourceEvidence = MobiResourceEvidence(
        href = href,
        mediaType = mediaType.toString(),
        byteCount = bytes.size,
        sha256 = sha256,
    )
}
