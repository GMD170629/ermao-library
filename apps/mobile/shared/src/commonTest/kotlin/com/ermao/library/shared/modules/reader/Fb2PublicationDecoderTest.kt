package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class Fb2PublicationDecoderTest {
    @Test
    fun nestedSectionAndOriginalIdsKeepServerAllocationOrder() {
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
        assertEquals("fb2/section-0001.xhtml#fb2-node-000002", publication.tableOfContents[0].children.single().href)
        assertEquals("fb2/section-0002.xhtml#fb2-node-000004", publication.tableOfContents[1].href)
        assertTrue(publication.resources.first().xhtml.contains("<p id=\"fb2-node-000003\">Before <strong>bold</strong> after</p>"))
    }

    @Test
    fun rejectsIncompleteDuplicateAndExcessivelyNestedXml() {
        val incomplete = Fb2PublicationDecoder()
        incomplete.startElement("FictionBook", emptyMap())
        assertFailsWith<IllegalArgumentException> { incomplete.finish("Book", emptyList()) }
        assertFailsWith<IllegalArgumentException> { incomplete.endElement("body") }
        repeat(127) { incomplete.startElement("section", emptyMap()) }
        assertFailsWith<IllegalArgumentException> { incomplete.startElement("section", emptyMap()) }

        val duplicate = Fb2PublicationDecoder()
        duplicate.element("FictionBook") {
            element("body") { repeat(2) { element("section", mapOf("id" to "same")) {} } }
        }
        assertFailsWith<IllegalArgumentException> { duplicate.finish("Book", emptyList()) }
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
