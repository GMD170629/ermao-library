package com.ermao.library.features.reader.infrastructure

import org.readium.r2.streamer.parser.epub.EpubPositionsService

import com.ermao.library.shared.modules.reader.TxtPublicationNormalizer
import java.io.File
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.Charset
import java.nio.charset.CodingErrorAction
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
import org.readium.r2.shared.util.resource.StringResource
import org.readium.r2.shared.util.resource.SingleResourceContainer
import org.readium.r2.shared.util.resource.Resource

internal class TxtReadiumPublicationFactory(
    private val normalizer: TxtPublicationNormalizer = TxtPublicationNormalizer(),
) {
    fun open(file: File, title: String): Publication {
        com.ermao.library.shared.modules.reader.ReaderAdmission.localFailure("txt", file.length())?.let {
            throw ReaderOpenFailure(com.ermao.library.shared.modules.reader.ReaderError(it))
        }
        val bytes = file.readBytes()
        val decoded = StrictTxtDecoder.decode(bytes)
        val normalized = normalizer.normalize(decoded, title)
        val readingOrder = normalized.resources.map { resource ->
            Link(
                href = requireNotNull(Url(resource.href)),
                mediaType = MediaType.XHTML,
                title = resource.title,
            )
        }
        val stylesheetLink = Link(
            href = requireNotNull(Url(normalized.stylesheetHref)),
            mediaType = MediaType.CSS,
        )
        val containers: List<Container<Resource>> = normalized.resources.map { resource ->
            SingleResourceContainer(
                requireNotNull(Url(resource.href)),
                StringResource(
                    EpubContentSecurityPolicy.generatedChapter(resource.xhtml)
                        .toString(Charsets.UTF_8),
                ),
            )
        } + listOf(SingleResourceContainer(
            requireNotNull(Url(normalized.stylesheetHref)),
            StringResource(normalized.stylesheet),
        ))
        return Publication(
            manifest = Manifest(
                metadata = Metadata(
                    identifier = "urn:shuku:txt:${file.nameWithoutExtension}",
                    type = "https://schema.org/Book",
                    conformsTo = setOf(Publication.Profile.EPUB),
                    localizedTitle = LocalizedString(normalized.title),
                    readingProgression = ReadingProgression.LTR,
                    layout = Layout.REFLOWABLE,
                ),
                readingOrder = readingOrder,
                resources = listOf(stylesheetLink),
                tableOfContents = readingOrder,
            ),
            container = CompositeContainer(containers),
            servicesBuilder = Publication.ServicesBuilder(
                positions = EpubPositionsService.createFactory(),
            ),
        )
    }
}

internal object StrictTxtDecoder {
    fun decode(bytes: ByteArray): String {
        val candidates = when {
            bytes.startsWith(byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte())) ->
                listOf(Charsets.UTF_8 to 3)
            bytes.startsWith(byteArrayOf(0xFF.toByte(), 0xFE.toByte())) ->
                listOf(Charsets.UTF_16LE to 2)
            bytes.startsWith(byteArrayOf(0xFE.toByte(), 0xFF.toByte())) ->
                listOf(Charsets.UTF_16BE to 2)
            else -> listOf(Charsets.UTF_8 to 0, Charset.forName("GB18030") to 0)
        }
        var lastFailure: CharacterCodingException? = null
        for ((charset, offset) in candidates) {
            try {
                return charset.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes, offset, bytes.size - offset))
                    .toString()
            } catch (failure: CharacterCodingException) {
                lastFailure = failure
            }
        }
        throw IllegalArgumentException("TXT publication encoding is unsupported", lastFailure)
    }

}

private fun ByteArray.startsWith(prefix: ByteArray): Boolean =
    size >= prefix.size && prefix.indices.all { this[it] == prefix[it] }
