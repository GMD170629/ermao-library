package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.readerSafetyFb2StructureFailure
import com.ermao.library.shared.modules.reader.readerSafetyFb2TextMaxBytes
import java.io.File
import java.io.RandomAccessFile
import java.nio.charset.Charset
import java.nio.file.Files
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test

class Fb2ReadiumPublicationFactoryTest {
    private val corpus = File("../../../test-data/library/fb2")

    @Test
    fun preservesRichContentAndMatchesServerExactAnchorsWithoutWritingDerivatives() {
        val file = File(corpus, "reader-contract.fb2")
        val original = file.readBytes()
        val before = corpus.listFiles()?.map { it.name }?.sorted()
        val parsed = Fb2SourceParser.read(file, "Fallback")
        val expected = Json.parseToJsonElement(File(corpus, "reader-contract-bodies.json").readText()).jsonObject

        assertEquals("阅读 & Reading", parsed.document.title)
        assertEquals("zh-CN", parsed.document.language)
        assertEquals(expected.keys.toList(), parsed.document.resources.map { it.href })
        parsed.document.resources.forEach { resource ->
            assertEquals(expected.getValue(resource.href).jsonPrimitive.content,
                resource.xhtml.substringAfter("<body>").substringBefore("</body>"))
        }
        assertEquals("fb2/section-0001.xhtml#chapter-node-20",
            parsed.document.tableOfContents.first().children.single().href)
        assertEquals(setOf("fb2/images/498cc84b29cb560e15b4.png"), parsed.images.keys)
        assertContentEquals(original, file.readBytes())
        assertEquals(before, corpus.listFiles()?.map { it.name }?.sorted())
    }

    @Test
    fun originalUpstreamFb2WithLegacyXlinkRemainsReadable() {
        val parsed = Fb2SourceParser.read(File(corpus, "source_test_book_fb2.fb2"), "Fallback")
        assertEquals("Sample FB2 book", parsed.document.title)
        assertTrue(parsed.document.resources.isNotEmpty())
    }

    @Test
    fun decodesDeclaredLegacyEncodingUtf16AndBodyWithoutSections() {
        val xml = """<?xml version="1.0" encoding="windows-1251"?>
            <!DOCTYPE FictionBook [<!ENTITY bodyText "Текст">]><FictionBook>
            <description><title-info><book-title>Книга</book-title></title-info></description>
            <body><p>&bodyText;</p></body></FictionBook>""".trimIndent()
        listOf(
            Charset.forName("windows-1251"), Charsets.UTF_8, Charsets.UTF_16,
            Charsets.UTF_16LE, Charsets.UTF_16BE,
        ).forEach { charset ->
            val bytes = xml.replace("windows-1251", charset.name()).toByteArray(charset)
            withSource(bytes) { file ->
                val parsed = Fb2SourceParser.read(file, "Fallback")
                assertEquals("Книга", parsed.document.title)
                assertTrue(parsed.document.resources.single().xhtml.contains("<p>Текст</p>"))
            }
        }
    }

    @Test
    fun rejectsActualXmlErrors() {
        val examples = listOf(
            "<FictionBook><body><p>broken</body></FictionBook>",
            "<FictionBook><body><section id='x'/><section id='x'/></body></FictionBook>",
            "<FictionBook><body><p l:href='#x'>unbound</p></body></FictionBook>",
        )
        examples.forEach { xml ->
            listOf(Charsets.UTF_8, Charsets.UTF_16).forEach { charset ->
                withSource(xml.toByteArray(charset)) { file ->
                    assertFailsWith<IllegalArgumentException> { Fb2SourceParser.read(file, "Fallback") }
                }
            }
        }
    }

    @Test
    fun safeDoctypePreservesUnicodeAndDeclaredCharsetText() {
        listOf(
            Triple("UTF-8", "中文正文", Charsets.UTF_8),
            Triple("windows-1252", "Café €", Charset.forName("windows-1252")),
        ).forEach { (encoding, text, charset) ->
            val xml = "<?xml version='1.0' encoding='$encoding'?><!DOCTYPE FictionBook>" +
                "<FictionBook><body><p>$text</p></body></FictionBook>"
            withSource(xml.toByteArray(charset)) { file ->
                assertTrue(Fb2SourceParser.read(file, "Book").document.resources.single().xhtml.contains("<p>$text</p>"))
            }
        }
    }

    @Test
    fun externalEntityIsLiteralizedWithoutReadingCanaryOrChangingOriginal() {
        val directory = Files.createTempDirectory("fb2-entity-canary").toFile()
        val canaryText = "FB2_EXTERNAL_ENTITY_CANARY_CONTENT"
        val canary = File(directory, "canary.txt").apply { writeText(canaryText) }
        try {
            listOf(Charsets.UTF_8, Charsets.UTF_16, Charsets.UTF_16LE, Charsets.UTF_16BE).forEach { charset ->
                listOf("", "&x;").forEach { reference ->
                    val xml = "<?xml version='1.0' encoding='${charset.name()}'?>" +
                        "<!DOCTYPE FictionBook [<!ENTITY x SYSTEM '${canary.toURI()}'>]>" +
                        "<FictionBook><body><p>中文${reference}END</p></body></FictionBook>"
                    withSource(xml.toByteArray(charset)) { file ->
                        val xhtml = Fb2SourceParser.read(file, "Book").document.resources.single().xhtml
                        val expectedReference = if (reference.isEmpty()) "" else "&amp;x;"
                        assertTrue(xhtml.contains("<p>中文${expectedReference}END</p>"))
                        assertFalse(xhtml.contains(canaryText))
                    }
                }
            }
            assertEquals(canaryText, canary.readText())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun unsupportedDeclaredEncodingFailsWithoutUtf8Fallback() {
        val xml = "<?xml version='1.0' encoding='not-a-charset'?><FictionBook><body><p>text</p></body></FictionBook>"
        withSource(xml.toByteArray()) { file ->
            assertFailsWith<IllegalArgumentException> { Fb2SourceParser.read(file, "Book") }
        }
    }

    @Test
    fun malformedEmbeddedImageIsBlockedWithoutRejectingReadableText() {
        val xml = "<FictionBook><body><p>text</p></body>" +
            "<binary id='image' content-type='image/png'>!!!!</binary></FictionBook>"
        withSource(xml.toByteArray()) { file ->
            val parsed = Fb2SourceParser.read(file, "Fallback")
            assertTrue(parsed.document.resources.single().xhtml.contains("<p>text</p>"))
            assertTrue(parsed.images.isEmpty())
            assertTrue(parsed.document.images.isEmpty())
        }
    }

    @Test
    fun passesEmbeddedBytesToTheImageDecoderWithoutSignatureValidation() {
        withSource("<FictionBook><body><p>text</p></body><binary id='image' content-type='image/png'>SGVsbG8=</binary></FictionBook>".toByteArray()) { file ->
            assertContentEquals("Hello".toByteArray(), Fb2SourceParser.read(file, "Book").images.values.single())
        }
    }

    @Test
    fun passesUnfamiliarImageMimeBytesToTheImageDecoderWithoutAnExtension() {
        withSource("<FictionBook><body><p>text</p></body><binary id='image' content-type='image/future-format'>SGVsbG8=</binary></FictionBook>".toByteArray()) { file ->
            val parsed = Fb2SourceParser.read(file, "Book")
            assertContentEquals("Hello".toByteArray(), parsed.images.values.single())
            assertEquals(setOf("fb2/images/6105d6cc76af400325e9"), parsed.images.keys)
            assertEquals("image/future-format", parsed.document.images.single().mediaType)
        }
    }

    @Test
    fun rejectsOversizedSourceBeforeMaterializingTheWholeFileWithGeneratedFailure() {
        val directory = Files.createTempDirectory("fb2-budget-test").toFile()
        val file = File(directory, "oversized.fb2")
        val sourceByteCount = readerSafetyFb2TextMaxBytes() + 1L
        try {
            RandomAccessFile(file, "rw").use { it.setLength(sourceByteCount) }

            val failure = assertFailsWith<ReaderSafetyException> {
                Fb2SourceParser.read(file, "Fallback")
            }

            assertEquals(readerSafetyFb2StructureFailure(), failure.failure)
            assertEquals(sourceByteCount, file.length())
        } finally {
            directory.deleteRecursively()
        }
    }

    private fun withSource(bytes: ByteArray, action: (File) -> Unit) {
        val directory = Files.createTempDirectory("fb2-parser-test").toFile()
        try {
            val file = File(directory, "original.fb2").apply { writeBytes(bytes) }
            action(file)
            assertContentEquals(bytes, file.readBytes())
            assertEquals(listOf("original.fb2"), directory.list()?.toList())
        } finally {
            directory.deleteRecursively()
        }
    }
}
