package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.Fb2ImageLink
import com.ermao.library.shared.modules.reader.Fb2PublicationDecoder
import com.ermao.library.shared.modules.reader.Fb2PublicationDocument
import com.ermao.library.shared.modules.reader.Fb2XmlPolicy
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
        val handler = object : DefaultHandler() {
            override fun startElement(uri: String?, localName: String, qName: String, attributes: Attributes) {
                decoder.startElement(localName, (0 until attributes.length).associate { index ->
                    attributes.getLocalName(index) to attributes.getValue(index)
                })
            }
            override fun characters(ch: CharArray, start: Int, length: Int) = decoder.text(String(ch, start, length))
            override fun endElement(uri: String?, localName: String, qName: String) = decoder.endElement(localName)
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
            val extension = readerSafetyFb2EmbeddedImageExtension(image.mediaType)
                ?: return@mapNotNull null
            totalBytes += contentSize
            val digest = MessageDigest.getInstance("SHA-256").digest(image.identifier.toByteArray())
                .take(10).joinToString("") { "%02x".format(it) }
            val href = "fb2/images/$digest$extension"
            images[href] = content
            Fb2ImageLink(image.identifier, href, image.mediaType)
        }
        return ParsedFb2Source(decoder.finish(fallbackTitle, links), images)
    }
}
