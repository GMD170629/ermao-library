package com.ermao.library.features.reader.infrastructure

import java.io.File
import java.nio.charset.Charset
import java.nio.file.Files
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
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
        assertEquals("fb2/section-0001.xhtml#fb2-node-000002",
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
        val xml = """<?xml version="1.0" encoding="windows-1251"?><FictionBook>
            <description><title-info><book-title>Книга</book-title></title-info></description>
            <body><p>Текст</p></body></FictionBook>""".trimIndent()
        listOf(xml.toByteArray(Charset.forName("windows-1251")),
            xml.replace("windows-1251", "UTF-16").toByteArray(Charsets.UTF_16)).forEach { bytes ->
            withSource(bytes) { file ->
                val parsed = Fb2SourceParser.read(file, "Fallback")
                assertEquals("Книга", parsed.document.title)
                assertTrue(parsed.document.resources.single().xhtml.contains("<p>Текст</p>"))
            }
        }
    }

    @Test
    fun rejectsActualXmlErrorsAndUnsafeEntities() {
        val examples = listOf(
            "<FictionBook><body><p>broken</body></FictionBook>",
            "<!DOCTYPE FictionBook [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><FictionBook><body><p>&x;</p></body></FictionBook>",
            "<FictionBook><body><section id='x'/><section id='x'/></body></FictionBook>",
            "<FictionBook><body><p l:href='#x'>unbound</p></body></FictionBook>",
            "<FictionBook><body><p>text</p></body><binary id='image' content-type='image/png'>!!!!</binary></FictionBook>",
        )
        examples.forEach { xml ->
            withSource(xml.toByteArray()) { file ->
                assertFailsWith<IllegalArgumentException> { Fb2SourceParser.read(file, "Fallback") }
            }
        }
        withSource(examples[1].toByteArray(Charsets.UTF_16)) { file ->
            assertFailsWith<IllegalArgumentException> { Fb2SourceParser.read(file, "Fallback") }
        }
    }

    @Test
    fun passesEmbeddedBytesToTheImageDecoderWithoutSignatureValidation() {
        withSource("<FictionBook><body><p>text</p></body><binary id='image' content-type='image/png'>SGVsbG8=</binary></FictionBook>".toByteArray()) { file ->
            assertContentEquals("Hello".toByteArray(), Fb2SourceParser.read(file, "Book").images.values.single())
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
