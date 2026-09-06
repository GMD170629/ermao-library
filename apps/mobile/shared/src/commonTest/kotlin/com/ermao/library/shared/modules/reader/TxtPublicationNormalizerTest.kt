package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertTrue

class TxtPublicationRendererTest {
    @Test
    fun rendersAlreadySegmentedTextWithStableEscaping() {
        val xhtml = renderTxtXhtml("测试 & 书", "前言 & <说明>\n\n正文一")
        assertTrue("前言 &amp; &lt;说明&gt;" in xhtml)
        assertTrue("id=\"block-000001\"" in xhtml)
    }

    @Test
    fun rendererPreservesNul() {
        val xhtml = renderTxtXhtml("Book", "a\u0000b\u0000")
        assertTrue("a\u0000b\u0000" in xhtml)
    }
}
