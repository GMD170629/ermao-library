package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyException
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class Fb2PublicationDecoderTest {
    @Test
    fun bodyTitleBeforeFirstSectionProducesReadableFirstResource() {
        val decoder = Fb2PublicationDecoder()
        decoder.element("FictionBook") {
            element("body") {
                element("title") { element("p") { text("This is a title") } }
                element("section") {
                    element("title") { element("p") { text("Test Header h1") } }
                    element("p") { text("A test paragraph.") }
                }
            }
        }

        val publication = decoder.finish("Sample FB2 book", emptyList())
        assertEquals(
            listOf("fb2/body-1-part-1.xhtml", "fb2/section-0001.xhtml"),
            publication.resources.map { it.href },
        )
        assertEquals(
            "<section><p>This is a title</p></section>",
            publication.resources.first().xhtml.substringAfter("<body>").substringBefore("</body>"),
        )
        assertEquals(
            "<section id=\"chapter-node-4\"><h1>Test Header h1</h1><p>A test paragraph.</p></section>",
            publication.resources.last().xhtml.substringAfter("<body>").substringBefore("</body>"),
        )
        assertTrue(publication.tableOfContents.isEmpty())
    }

    @Test
    fun nestedSectionAndOriginalIdsKeepGlobalSourceOrdinals() {
        val decoder = Fb2PublicationDecoder()
        decoder.element("FictionBook") {
            element("body") {
                element("section", mapOf("id" to "chapter")) {
                    element("p", mapOf("id" to "opening")) {
                        text("Before ")
                        element("strong") { text("bold") }
                        text(" after")
                    }
                    element("section", mapOf("id" to "nested")) { element("p") { text("Nested") } }
                }
            }
            element("body") { element("section", mapOf("id" to "note")) { element("p") { text("Note") } } }
        }
        val publication = decoder.finish("Book", emptyList())
        assertEquals(emptyList(), publication.tableOfContents)
        assertEquals(
            listOf("fb2/section-0001.xhtml", "fb2/section-0002.xhtml"),
            publication.resources.map { it.href },
        )
        assertTrue(publication.resources.first().xhtml.contains("<section id=\"chapter-node-2\">"))
        assertTrue(publication.resources.first().xhtml.contains("<p id=\"chapter-node-3\">Before <strong>bold</strong> after</p>"))
        assertTrue(publication.resources.first().xhtml.contains("<section id=\"chapter-node-5\">")
        )
        assertTrue(!publication.resources.first().xhtml.contains("<h1>Book</h1>"))
        assertTrue(publication.resources.all { !it.xhtml.contains("fb2-node-") })
    }

    @Test
    fun preservesLooseBodyRunsAndMixedContentInSourceOrder() {
        val decoder = Fb2PublicationDecoder()
        decoder.element("FictionBook") {
            element("body") {
                text("Before ")
                element("p") { text("first") }
                text("\n")
                element("section") {
                    element("title") { text("One") }
                    text("lead ")
                    element("p") { text("inside") }
                    text(" tail")
                    element("section") {
                        element("title") { text("Nested") }
                        text("nested text")
                    }
                    text(" after nested")
                }
                text("\nAfter ")
                element("title") {
                    element("p") {
                        text("Title & ")
                        element("strong") { text("<bold>") }
                        text(" tail")
                    }
                }
                text("\n")
                element("p") { text("last") }
            }
        }

        val publication = decoder.finish("Book", emptyList())
        assertEquals(
            listOf(
                "fb2/body-1-part-1.xhtml",
                "fb2/section-0001.xhtml",
                "fb2/body-1-part-2.xhtml",
            ),
            publication.resources.map { it.href },
        )
        val first = publication.resources[0].xhtml
        val section = publication.resources[1].xhtml
        val last = publication.resources[2].xhtml
        assertTrue(first.indexOf("Before") < first.indexOf("<p>first</p>"))
        assertTrue(section.indexOf("lead ") < section.indexOf("<p>inside</p>"))
        assertTrue(section.indexOf("<p>inside</p>") < section.indexOf(" tail"))
        assertTrue(section.indexOf(" tail") < section.indexOf("<section id=\"chapter-node-6\">")
        )
        assertTrue(section.indexOf("nested text") < section.indexOf(" after nested"))
        assertEquals(
            "<section id=\"chapter-node-3\"><h1>One</h1>lead <p>inside</p> tail" +
                "<section id=\"chapter-node-6\"><h2>Nested</h2>nested text</section> after nested</section>",
            section.substringAfter("<body>").substringBefore("</body>"),
        )
        assertEquals(
            "<section>\nAfter <p>Title &amp; <strong>&lt;bold&gt;</strong> tail</p>\n<p>last</p></section>",
            last.substringAfter("<body>").substringBefore("</body>"),
        )
        assertTrue(publication.tableOfContents.isEmpty())
    }

    @Test
    fun suppliedSourceOrdinalMustMatchDecoderEventOrder() {
        val decoder = Fb2PublicationDecoder()
        assertFailsWith<IllegalArgumentException> {
            decoder.startElement("FictionBook", emptyMap(), sourceStart = 1L)
        }
    }

    @Test
    fun rejectsIncompleteDuplicateAndExcessivelyNestedXml() {
        val incomplete = Fb2PublicationDecoder()
        incomplete.startElement("FictionBook", emptyMap())
        assertFailsWith<IllegalArgumentException> { incomplete.finish("Book", emptyList()) }
        assertFailsWith<IllegalArgumentException> { incomplete.endElement("body") }
        repeat(ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_MAX_DEPTH).toInt() - 1) {
            incomplete.startElement("section", emptyMap())
        }
        val failure = assertFailsWith<ReaderSafetyException> {
            incomplete.startElement("section", emptyMap())
        }
        assertEquals("FB2.STRUCTURE_BUDGET", failure.failure.ruleId)
        assertEquals("PUBLICATION_PARSER_LIMIT", failure.failure.errorCode)

        val duplicate = Fb2PublicationDecoder()
        duplicate.element("FictionBook") {
            element("body") { repeat(2) { element("section", mapOf("id" to "same")) {} } }
        }
        assertFailsWith<IllegalArgumentException> { duplicate.finish("Book", emptyList()) }
    }

    @Test
    fun generatedEmbeddedImageCatalogAllowsBlockedResourcesToBeOmitted() {
        val decoder = Fb2PublicationDecoder()
        decoder.element("FictionBook") {
            element("body") { element("section") { element("p") { text("Readable") } } }
            element("binary", mapOf("id" to "bad", "content-type" to "image/png")) {
                text("not-base64")
            }
        }

        assertEquals(listOf("bad"), decoder.embeddedImages().map { it.identifier })
        assertTrue(decoder.finish("Book", emptyList()).resources.isNotEmpty())
    }

    @Test
    fun preservesEmbeddedImageBytesWhenMimeHasNoGeneratedExtension() {
        val decoder = Fb2PublicationDecoder()
        decoder.element("FictionBook") {
            element("body") { element("section") { element("p") { text("Readable") } } }
            element("binary", mapOf("id" to "future", "content-type" to "image/future-format")) {
                text("SGVsbG8=")
            }
        }

        val image = decoder.embeddedImages().single()
        assertEquals("image/future-format", image.mediaType)
        val document = decoder.finish(
            "Book",
            listOf(Fb2ImageLink("future", "fb2/images/01234567890123456789", image.mediaType)),
        )

        assertEquals("fb2/images/01234567890123456789", document.images.single().href)
    }

    @Test
    fun legacyLinkRepairRequiresAnExplicitStandardNamespaceAndRejectsDeclarations() {
        val policy = Fb2XmlPolicy()
        val xml = "<FictionBook xmlns:xlink='http://www.w3.org/1999/xlink'><a l:href='#note'/></FictionBook>"
        assertTrue(policy.prepare(xml).contains("xlink:href='#note'"))
        val bound = xml.replace("xmlns:xlink", "xmlns:l")
        assertEquals(bound, policy.prepare(bound))
        val unbound = "<FictionBook><a l:href='#note'/></FictionBook>"
        assertEquals(unbound, policy.prepare(unbound))
        listOf("<!DOCTYPE FictionBook>", "<!ENTITY x 'text'>").forEach { declaration ->
            assertFailsWith<IllegalArgumentException> { policy.prepare(declaration + xml) }
            assertFailsWith<IllegalArgumentException> { policy.prepare(declaration.toCharArray().joinToString("\u0000") + xml) }
        }
    }

    private fun Fb2PublicationDecoder.element(name: String, attributes: Map<String, String> = emptyMap(), content: Fb2PublicationDecoder.() -> Unit) {
        startElement(name, attributes)
        content()
        endElement(name)
    }
}
