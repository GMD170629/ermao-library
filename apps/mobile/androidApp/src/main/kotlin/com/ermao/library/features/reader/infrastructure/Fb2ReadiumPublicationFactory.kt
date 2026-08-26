package com.ermao.library.features.reader.infrastructure

import java.io.File
import java.io.StringReader
import javax.xml.XMLConstants
import javax.xml.parsers.SAXParserFactory
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
import org.readium.r2.shared.util.resource.Resource
import org.readium.r2.shared.util.resource.SingleResourceContainer
import org.readium.r2.shared.util.resource.StringResource
import org.xml.sax.Attributes
import org.xml.sax.InputSource
import org.xml.sax.helpers.DefaultHandler

internal class Fb2ReadiumPublicationFactory {
    fun open(file: File, fallbackTitle: String): Publication {
        require(file.length() in 1..MAXIMUM_FB2_BYTES) { "FB2 source exceeds the size limit" }
        val bytes = file.readBytes()
        val declarationProbe = bytes.toString(Charsets.ISO_8859_1)
        require(!UNSAFE_XML.containsMatchIn(declarationProbe)) {
            "FB2 contains unsafe XML declarations"
        }
        val document = parse(bytes, fallbackTitle)
        val resources = document.sections.mapIndexed { index, section ->
            val href = "fb2/section-${(index + 1).toString().padStart(4, '0')}.xhtml"
            val title = section.title.ifBlank { "${document.title} ${index + 1}" }
            val content = section.blocks.joinToString("\n") { block ->
                when (block.kind) {
                    Fb2BlockKind.Heading -> "<h2 id=\"fb2-node-${block.index}\">${block.text.escapeXml()}</h2>"
                    Fb2BlockKind.Paragraph -> "<p id=\"fb2-node-${block.index}\">${block.text.escapeXml()}</p>"
                }
            }
            val xhtml = """<?xml version="1.0" encoding="utf-8"?>
                |<html xmlns="http://www.w3.org/1999/xhtml"><head><title>${title.escapeXml()}</title>
                |<link rel="stylesheet" type="text/css" href="reader.css"/></head>
                |<body><section>$content</section></body></html>
            """.trimMargin()
            Fb2Resource(href, title, xhtml)
        }
        val readingOrder = resources.map { resource ->
            Link(
                href = requireNotNull(Url(resource.href)),
                mediaType = MediaType.XHTML,
                title = resource.title,
            )
        }
        val stylesheetHref = "fb2/reader.css"
        val containers: List<Container<Resource>> = resources.map { resource ->
            SingleResourceContainer(
                requireNotNull(Url(resource.href)),
                StringResource(
                    EpubContentSecurityPolicy.decorateHtml(resource.xhtml.toByteArray())
                        .toString(Charsets.UTF_8),
                ),
            )
        } + listOf(
            SingleResourceContainer(
                requireNotNull(Url(stylesheetHref)),
                StringResource(FB2_STYLESHEET),
            ),
        )
        return Publication(
            manifest = Manifest(
                metadata = Metadata(
                    identifier = "urn:shuku:fb2:${file.nameWithoutExtension}",
                    type = "https://schema.org/Book",
                    conformsTo = setOf(Publication.Profile.EPUB),
                    localizedTitle = LocalizedString(document.title),
                    readingProgression = ReadingProgression.LTR,
                    layout = Layout.REFLOWABLE,
                ),
                readingOrder = readingOrder,
                resources = listOf(
                    Link(
                        href = requireNotNull(Url(stylesheetHref)),
                        mediaType = MediaType.CSS,
                    ),
                ),
                tableOfContents = readingOrder,
            ),
            container = CompositeContainer(containers),
        )
    }

    private fun parse(bytes: ByteArray, fallbackTitle: String): Fb2Document {
        val factory = SAXParserFactory.newInstance().apply {
            isNamespaceAware = true
            setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true)
            setFeature("http://xml.org/sax/features/external-general-entities", false)
            setFeature("http://xml.org/sax/features/external-parameter-entities", false)
            setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false)
        }
        val handler = Fb2Handler(fallbackTitle)
        factory.newSAXParser().xmlReader.apply {
            entityResolver = org.xml.sax.EntityResolver { _, _ -> InputSource(StringReader("")) }
            contentHandler = handler
            errorHandler = handler
        }.parse(InputSource(bytes.inputStream()))
        return handler.document()
    }

    private companion object {
        const val MAXIMUM_FB2_BYTES = 64L * 1024 * 1024
        val UNSAFE_XML = Regex("<!DOCTYPE\\b|<!ENTITY\\b", RegexOption.IGNORE_CASE)
        val FB2_STYLESHEET = """
            body { margin: 0; padding: 1rem; line-height: 1.6; overflow-wrap: anywhere; }
            section { margin: 0 0 2rem; } h2 { line-height: 1.3; }
            p { margin: 0 0 1em; }
        """.trimIndent()
    }
}

private class Fb2Handler(private val fallbackTitle: String) : DefaultHandler() {
    private val path = mutableListOf<String>()
    private val sections = mutableListOf<MutableFb2Section>()
    private var currentSection: MutableFb2Section? = null
    private var sectionDepth = 0
    private var elementCount = 0
    private var blockIndex = 0
    private var capture: StringBuilder? = null
    private var captureElement: String? = null
    private var bookTitle: String? = null

    override fun startElement(uri: String?, localName: String?, qName: String?, attributes: Attributes?) {
        val name = (localName?.takeIf(String::isNotBlank) ?: qName.orEmpty().substringAfterLast(':')).lowercase()
        elementCount += 1
        require(elementCount <= MAXIMUM_ELEMENTS) { "FB2 contains too many XML elements" }
        require(path.size < MAXIMUM_DEPTH) { "FB2 XML nesting is too deep" }
        if (path.isEmpty()) require(name == "fictionbook") { "FB2 root element is invalid" }
        path += name
        if (name == "section" && "body" in path) {
            if (sectionDepth == 0) {
                currentSection = MutableFb2Section().also(sections::add)
                require(sections.size <= MAXIMUM_SECTIONS) { "FB2 contains too many sections" }
            }
            sectionDepth += 1
        }
        if (name == "p" || name == "subtitle" || name == "v" || name == "text-author") {
            capture = StringBuilder()
            captureElement = name
        }
    }

    override fun characters(ch: CharArray, start: Int, length: Int) {
        capture?.append(ch, start, length)
        require((capture?.length ?: 0) <= MAXIMUM_BLOCK_CHARS) { "FB2 text block exceeds the size limit" }
    }

    override fun endElement(uri: String?, localName: String?, qName: String?) {
        val name = (localName?.takeIf(String::isNotBlank) ?: qName.orEmpty().substringAfterLast(':')).lowercase()
        if (name == captureElement) {
            val text = capture.toString().normalizeWhitespace()
            if (text.isNotEmpty()) {
                if (path.contains("description") && path.contains("book-title")) {
                    bookTitle = text
                } else if ("body" in path) {
                    val section = currentSection ?: MutableFb2Section().also {
                        sections += it
                        currentSection = it
                    }
                    blockIndex += 1
                    require(blockIndex <= MAXIMUM_BLOCKS) { "FB2 contains too many text blocks" }
                    val heading = path.contains("title") || name == "subtitle"
                    section.blocks += Fb2Block(
                        index = blockIndex,
                        kind = if (heading) Fb2BlockKind.Heading else Fb2BlockKind.Paragraph,
                        text = text,
                    )
                    if (heading && section.title.isBlank()) section.title = text
                }
            }
            capture = null
            captureElement = null
        }
        if (name == "section" && sectionDepth > 0) {
            sectionDepth -= 1
            if (sectionDepth == 0) currentSection = null
        }
        require(path.lastOrNull() == name) { "FB2 XML nesting is invalid" }
        path.removeAt(path.lastIndex)
    }

    fun document(): Fb2Document {
        val nonEmpty = sections.filter { it.blocks.isNotEmpty() }
        require(nonEmpty.isNotEmpty()) { "FB2 reading order is empty" }
        return Fb2Document(
            title = bookTitle?.takeIf(String::isNotBlank) ?: fallbackTitle,
            sections = nonEmpty.map { Fb2Section(it.title, it.blocks.toList()) },
        )
    }

    private companion object {
        const val MAXIMUM_ELEMENTS = 200_000
        const val MAXIMUM_DEPTH = 128
        const val MAXIMUM_SECTIONS = 10_000
        const val MAXIMUM_BLOCKS = 200_000
        const val MAXIMUM_BLOCK_CHARS = 1_000_000
    }
}

private data class Fb2Document(val title: String, val sections: List<Fb2Section>)
private data class Fb2Section(val title: String, val blocks: List<Fb2Block>)
private class MutableFb2Section(var title: String = "", val blocks: MutableList<Fb2Block> = mutableListOf())
private data class Fb2Resource(val href: String, val title: String, val xhtml: String)
private data class Fb2Block(val index: Int, val kind: Fb2BlockKind, val text: String)
private enum class Fb2BlockKind { Heading, Paragraph }

private fun String.normalizeWhitespace(): String = replace(Regex("[\\s\\p{Z}]+"), " ").trim()

private fun String.escapeXml(): String = buildString(length) {
    this@escapeXml.forEach { character ->
        append(
            when (character) {
                '&' -> "&amp;"
                '<' -> "&lt;"
                '>' -> "&gt;"
                '"' -> "&quot;"
                '\'' -> "&apos;"
                else -> character
            },
        )
    }
}
