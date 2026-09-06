package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.Fb2ImageLink
import com.ermao.library.shared.modules.reader.Fb2PublicationDecoder
import com.ermao.library.shared.modules.reader.Fb2PublicationDocument
import com.ermao.library.shared.modules.reader.Fb2XmlPolicy
import com.ermao.library.chapter.infrastructure.ChapterCore
import com.ermao.library.chapter.infrastructure.ChapterCoreResult
import com.ermao.library.chapter.infrastructure.ChapterCoreXmlAttribute
import com.ermao.library.chapter.infrastructure.ChapterCoreXmlEvent
import com.ermao.library.shared.modules.reader.Fb2NavigationEntry
import com.ermao.library.shared.modules.reader.ReaderAdmission
import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.readerSafetyFb2DecodedImageMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyFb2DecodedImagesTotalMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyFb2EmbeddedImageExtension
import com.ermao.library.shared.modules.reader.readerSafetyFb2TextBudgetFailure
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest
import java.util.Base64
import javax.xml.parsers.SAXParserFactory
import org.xml.sax.Attributes
import org.xml.sax.InputSource
import org.xml.sax.SAXException
import org.xml.sax.SAXParseException
import org.xml.sax.helpers.DefaultHandler

internal data class ParsedFb2Source(val document: Fb2PublicationDocument, val images: Map<String, ByteArray>)

internal object Fb2SourceParser {
    fun read(file: File, fallbackTitle: String): ParsedFb2Source {
        val sourceByteCount = file.length()
        ReaderAdmission.localSafetyFailure("fb2", sourceByteCount)?.let { throw ReaderSafetyException(it) }
        readerSafetyFb2TextBudgetFailure(sourceByteCount)?.let { throw ReaderSafetyException(it) }
        val bytes = file.inputStream().use { input ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            var sourceBytesRead = 0L
            var count = input.read(buffer)
            while (count != -1) {
                sourceBytesRead += count.toLong()
                readerSafetyFb2TextBudgetFailure(sourceBytesRead)?.let { throw ReaderSafetyException(it) }
                output.write(buffer, 0, count)
                count = input.read(buffer)
            }
            output.toByteArray()
        }
        val prepared = Fb2XmlPolicy().prepare(bytes.toString(Charsets.ISO_8859_1)).toByteArray(Charsets.ISO_8859_1)
        val decoder = Fb2PublicationDecoder()
        val chapterEvents = mutableListOf<ChapterCoreXmlEvent>()
        var sourceOrdinal = 0L
        var bodyDepth = 0
        var topSectionCount = 0
        val sectionHrefs = ArrayDeque<String>()
        val handler = object : DefaultHandler() {
            override fun startElement(uri: String?, localName: String, qName: String, attributes: Attributes) {
                val name = localName.ifBlank { qName.substringAfterLast(':') }
                val ordinal = sourceOrdinal++
                if (name == "body") bodyDepth += 1
                val targetHref = if (name == "section" && bodyDepth > 0) {
                    val href = sectionHrefs.lastOrNull() ?: run {
                        topSectionCount += 1
                        "fb2/section-${topSectionCount.toString().padStart(4, '0')}.xhtml"
                    }
                    sectionHrefs.addLast(href)
                    "$href#chapter-node-$ordinal"
                } else {
                    null
                }
                val mappedAttributes = (0 until attributes.length).associate { index ->
                    val attributeName = attributes.getLocalName(index).ifBlank {
                        attributes.getQName(index).substringAfterLast(':')
                    }
                    attributeName to attributes.getValue(index)
                }
                decoder.startElement(name, mappedAttributes, sourceStart = ordinal)
                chapterEvents += ChapterCoreXmlEvent(
                    kind = 1,
                    name = name,
                    attributes = mappedAttributes.map { (key, value) ->
                        ChapterCoreXmlAttribute(key, value)
                    }.toTypedArray(),
                    href = targetHref,
                )
            }
            override fun characters(ch: CharArray, start: Int, length: Int) {
                val value = String(ch, start, length)
                decoder.text(value)
                if (value.isNotEmpty()) chapterEvents += ChapterCoreXmlEvent(kind = 2, text = value)
            }
            override fun endElement(uri: String?, localName: String, qName: String) {
                val name = localName.ifBlank { qName.substringAfterLast(':') }
                decoder.endElement(name)
                chapterEvents += ChapterCoreXmlEvent(kind = 3, name = name)
                if (name == "section" && sectionHrefs.isNotEmpty()) sectionHrefs.removeLast()
                if (name == "body") bodyDepth -= 1
            }
            override fun error(exception: SAXParseException): Nothing = throw exception
            override fun fatalError(exception: SAXParseException): Nothing = throw exception
        }
        // Android's Expat does not implement Xerces feature URIs. Reject declarations before
        // parsing and reject all entity resolution instead of depending on optional flags.
        try {
            SAXParserFactory.newInstance().apply { isNamespaceAware = true }.newSAXParser().xmlReader.apply {
                entityResolver = org.xml.sax.EntityResolver { _, _ -> throw SAXException("External XML is prohibited") }
                contentHandler = handler
                errorHandler = handler
            }.parse(InputSource(prepared.inputStream()))
        } catch (error: SAXException) {
            throw IllegalArgumentException("FB2 XML is invalid", error)
        }
        var totalBytes = 0L
        val images = mutableMapOf<String, ByteArray>()
        val links = decoder.embeddedImages().mapNotNull { image ->
            val content = runCatching { Base64.getDecoder().decode(image.encoded) }.getOrNull()
                ?: return@mapNotNull null
            val contentSize = content.size.toLong()
            if (contentSize > readerSafetyFb2DecodedImageMaxBytes() ||
                contentSize > readerSafetyFb2DecodedImagesTotalMaxBytes() - totalBytes
            ) {
                return@mapNotNull null
            }
            // The content type is decoder input, not an admission allowlist. Unknown image
            // types retain their original bytes under a stable extensionless virtual href.
            val extension = readerSafetyFb2EmbeddedImageExtension(image.mediaType).orEmpty()
            totalBytes += contentSize
            val digest = MessageDigest.getInstance("SHA-256").digest(image.identifier.toByteArray())
                .take(10).joinToString("") { "%02x".format(it) }
            val href = "fb2/images/$digest$extension"
            images[href] = content
            Fb2ImageLink(image.identifier, href, image.mediaType)
        }
        val document = decoder.finish(fallbackTitle, links)
        val projection = ChapterCore.parseXml(format = 3, events = chapterEvents)
        return ParsedFb2Source(document.copy(tableOfContents = projection.toNavigation()), images)
    }

    private fun ChapterCoreResult.toNavigation(): List<Fb2NavigationEntry> {
        val childrenByParent = entries.indices.groupBy { entries[it].parentIndex }
        fun node(index: Int): Fb2NavigationEntry {
            val entry = entries[index]
            val children = childrenByParent[index].orEmpty().map(::node)
            return Fb2NavigationEntry(
                href = entry.href,
                title = entry.title,
                children = children,
                navigationKey = entry.key,
            )
        }
        return childrenByParent[null].orEmpty().map(::node)
    }
}
