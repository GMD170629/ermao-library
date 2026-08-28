package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class TxtPublicationNormalizerTest {
    @Test
    fun normalizesNewlinesChaptersStableIdsAndEscaping() {
        val publication = TxtPublicationNormalizer().normalize(
            "前言 & <说明>\r\n\r\n第一章 开始\r正文一\r\rChapter 2: Next\r\n正文二",
            "测试 & 书",
        )

        assertEquals(
            listOf("text/chapter-0001.xhtml", "text/chapter-0002.xhtml", "text/chapter-0003.xhtml"),
            publication.resources.map { it.href },
        )
        assertTrue("前言 &amp; &lt;说明&gt;" in publication.resources.first().xhtml)
        assertTrue("id=\"block-000001\"" in publication.resources.first().xhtml)
        assertEquals("第一章 开始", publication.resources[1].title)
        assertEquals(publication, TxtPublicationNormalizer().normalize(
            "前言 & <说明>\n\n第一章 开始\n正文一\n\nChapter 2: Next\n正文二",
            "测试 & 书",
        ))
    }

    @Test
    fun rejectsEmptyButPreservesNulForTheRenderer() {
        assertFailsWith<IllegalArgumentException> { TxtPublicationNormalizer().normalize(" \n", "Book") }
        val publication = TxtPublicationNormalizer().normalize("a\u0000b\u0000", "Book")
        assertTrue("a\u0000b\u0000" in publication.resources.single().xhtml)
    }
}
