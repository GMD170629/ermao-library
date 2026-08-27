package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class MobiMarkupEnvelopeTest {
    @Test
    fun legacyMobiGetsXhtmlAndPageBreakNamespacesWithoutChangingBody() {
        val body = "<p id=\"chapter\">正文</p><mbp:pagebreak/><p>Next</p>"
        val source = "<html><head></head><body>$body</body></html>"
        val prepared = MobiMarkupEnvelope().prepare(source)
        assertTrue(prepared.startsWith("<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:mbp="))
        assertEquals(body, prepared.substringAfter("<body>").substringBefore("</body>"))
        assertEquals(prepared, MobiMarkupEnvelope().prepare(prepared))
    }

    @Test
    fun declaredNamespacesAndFakeRootsAreNeverRewritten() {
        val source = """<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:mbp="urn:original"><head/><body/></html>"""
        assertEquals(source, MobiMarkupEnvelope().prepare(source))
        val fake = "<!-- <html> --><other><head/><body/></other>"
        assertEquals(fake, MobiMarkupEnvelope().prepare(fake))
    }
}
