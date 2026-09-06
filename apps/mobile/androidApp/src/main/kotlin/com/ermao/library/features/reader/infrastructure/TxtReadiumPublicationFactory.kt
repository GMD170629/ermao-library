package com.ermao.library.features.reader.infrastructure

import org.readium.r2.streamer.parser.epub.EpubPositionsService

import com.ermao.library.chapter.infrastructure.ChapterCore
import com.ermao.library.shared.modules.reader.NormalizedTxtResource
import com.ermao.library.shared.modules.reader.domain.renderTxtXhtml
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

internal class TxtReadiumPublicationFactory {
    fun open(file: File, title: String): Publication {
        com.ermao.library.shared.modules.reader.ReaderAdmission.localFailure("txt", file.length())?.let {
            throw ReaderOpenFailure(com.ermao.library.shared.modules.reader.ReaderError(it))
        }
        val bytes = file.readBytes()
        val decoded = StrictTxtDecoder.decode(bytes)
        val core = ChapterCore.parseTxt(decoded)
        if (core.text.isBlank()) {
            throw com.ermao.library.shared.modules.reader.TxtPublicationEmptyException()
        }
        val normalizedResources = txtResources(core, title)
        val readingOrder = normalizedResources.map { resource ->
            Link(
                href = requireNotNull(Url(resource.href)),
                mediaType = MediaType.XHTML,
                title = resource.title,
            )
        }
        val stylesheetLink = Link(
            href = requireNotNull(Url("text/reader.css")),
            mediaType = MediaType.CSS,
        )
        val containers: List<Container<Resource>> = normalizedResources.map { resource ->
            SingleResourceContainer(
                requireNotNull(Url(resource.href)),
                StringResource(
                    EpubContentSecurityPolicy.generatedChapter(resource.xhtml)
                        .toString(Charsets.UTF_8),
                ),
            )
        } + listOf(SingleResourceContainer(
            requireNotNull(Url("text/reader.css")),
            StringResource(TXT_STYLESHEET),
        ))
        return Publication(
            manifest = Manifest(
                metadata = Metadata(
                    identifier = "urn:shuku:txt:${file.nameWithoutExtension}",
                    type = "https://schema.org/Book",
                    conformsTo = setOf(Publication.Profile.EPUB),
                    localizedTitle = LocalizedString(title),
                    readingProgression = ReadingProgression.LTR,
                    layout = Layout.REFLOWABLE,
                ),
                readingOrder = readingOrder,
                resources = listOf(stylesheetLink),
                tableOfContents = core.entries.map { entry ->
                        Link(
                            href = requireNotNull(Url(requireNotNull(entry.href))),
                            mediaType = MediaType.XHTML,
                            title = entry.title,
                        ).addProperties(mapOf("shuku:navigationKey" to entry.key))
                    },
            ),
            container = CompositeContainer(containers),
            servicesBuilder = Publication.ServicesBuilder(
                positions = EpubPositionsService.createFactory(),
            ),
        )
    }

    private fun txtResources(
        result: com.ermao.library.chapter.infrastructure.ChapterCoreResult,
        title: String,
    ): List<NormalizedTxtResource> {
        val bytes = result.text.encodeToByteArray()
        val entries = result.entries
        if (entries.isEmpty()) {
            return listOf(
                NormalizedTxtResource(
                    href = "text/body.xhtml",
                    title = title,
                    xhtml = renderTxtXhtml(title, result.text),
                ),
            )
        }
        return buildList {
            val firstStart = entries.first().sourceStart
            if (firstStart > 0L) {
                add(NormalizedTxtResource(
                    href = "text/frontmatter.xhtml",
                    title = title,
                    xhtml = renderTxtXhtml(title, utf8Slice(bytes, 0L, firstStart)),
                ))
            }
            entries.forEach { entry ->
                val href = requireNotNull(entry.href)
                add(NormalizedTxtResource(
                    href = href.substringBefore('#'),
                    title = entry.title,
                    xhtml = renderTxtXhtml(
                        entry.title,
                        utf8Slice(bytes, entry.contentStart, entry.sourceEnd),
                    ),
                ))
            }
        }.also { require(it.isNotEmpty()) { "TXT publication has no readable resources" } }
    }

    private fun utf8Slice(bytes: ByteArray, start: Long, end: Long): String {
        require(start in 0L..bytes.size.toLong() && end in start..bytes.size.toLong()) {
            "TXT chapter core returned an invalid UTF-8 range"
        }
        val decoder = Charsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
        return decoder.decode(ByteBuffer.wrap(bytes, start.toInt(), (end - start).toInt())).toString()
    }
}

private const val TXT_STYLESHEET = """html { color-scheme: light dark; }
body { margin: 0; padding: 1rem; line-height: 1.6; overflow-wrap: anywhere; }
h1 { font-size: 1.35em; margin: 1.5em 0 1em; }
p { margin: 0 0 1em; white-space: normal; }
"""

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
