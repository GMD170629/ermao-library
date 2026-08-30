package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyMarkupResult
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ReaderSafetyFacadeTest {
    private val facade = ReaderSafetyFacade()

    @Test
    fun sanitizesDangerousBodyUsingGeneratedProfileAndKeepsParserProjectionInputInMemory() {
        val markup = """<?xml version="1.0" encoding="utf-8"?>
            <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
            <html xmlns="http://www.w3.org/1999/xhtml"><head>
              <base href="https://attacker.invalid/"/><meta http-equiv="refresh" content="0;https://attacker.invalid/"/>
            </head><body onload="steal()"><h1 id="title">Readable&nbsp;&copy;</h1><script>steal()</script>
              <form><p>removed with dangerous container</p></form><iframe src="remote"/>
            </body></html>""".trimIndent()

        val accepted = assertIs<ReaderSafetyMarkupResult.Accepted>(facade.sanitizeMarkup(markup))

        assertTrue(accepted.value.changed)
        assertTrue(accepted.value.markup.contains("<h1 id=\"title\">Readable&nbsp;&copy;</h1>"))
        assertFalse(accepted.value.markup.contains("<script"))
        assertFalse(accepted.value.markup.contains("<form"))
        assertFalse(accepted.value.markup.contains("onload="))
        assertFalse(accepted.value.markup.contains("http-equiv=\"refresh\""))
        assertFalse(accepted.value.markup.contains("<iframe"))
        assertTrue(accepted.value.parserMarkup.contains("Readable&#160;&#169;"))
    }

    @Test
    fun rejectsCustomEntitiesWithGeneratedRuleAndStableErrorCode() {
        val rejected = assertIs<ReaderSafetyMarkupResult.Rejected>(facade.sanitizeMarkup(
            "<!DOCTYPE html [<!ENTITY x SYSTEM \"file:///tmp/secret\">]><html><head></head><body>&x;</body></html>",
        ))

        assertEquals("REFLOWABLE.REJECT_XML_ENTITY", rejected.failure.ruleId)
        assertEquals("PUBLICATION_SECURITY_REJECTED", rejected.failure.errorCode)
    }

    @Test
    fun rejectsBareDoctypeAndUnknownNamedEntity() {
        listOf(
            "<!DOCTYPE html><html><head></head><body>text</body></html>",
            """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd"><html><head></head><body>&custom;</body></html>""",
        ).forEach { markup ->
            val rejected = assertIs<ReaderSafetyMarkupResult.Rejected>(facade.sanitizeMarkup(markup))
            assertEquals("REFLOWABLE.REJECT_XML_ENTITY", rejected.failure.ruleId)
            assertEquals("PUBLICATION_SECURITY_REJECTED", rejected.failure.errorCode)
        }
    }

    @Test
    fun generatedUriAndCssPoliciesKeepNavigationAndRemoveActiveSubresources() {
        val markup = """<html><head><style>@import url(https://example.test/x.css);p{behavior:url(x);color:red}</style></head><body><a href="https://example.test/read">read</a><img src="https://example.test/cover.jpg" srcset="local.png 1x, //example.test/remote.png 2x"/><p style="color:red;background:url(javascript:alert(1))">safe</p></body></html>"""

        val accepted = assertIs<ReaderSafetyMarkupResult.Accepted>(facade.sanitizeMarkup(markup))

        assertTrue(accepted.value.markup.contains("<style>p{color:red}</style>"))
        assertTrue(accepted.value.markup.contains("href=\"https://example.test/read\""))
        assertFalse(accepted.value.markup.contains("src=\"https://example.test/cover.jpg\""))
        assertTrue(accepted.value.markup.contains("srcset=\"local.png 1x\""))
        assertFalse(accepted.value.markup.contains("javascript:"))
        assertFalse(accepted.value.markup.contains("example.test/remote.png"))
    }

    @Test
    fun unavailablePolicyAlgorithmIsNotReportedAsAContentRejection() {
        val failure = facade.platformFailureFor(ReaderSafetyRuleId.REFLOWABLE_SANITIZE_CSS)

        assertEquals("REFLOWABLE.SANITIZE_CSS", failure.ruleId)
        assertEquals("PLATFORM_POLICY_ALGORITHM_UNSUPPORTED", failure.errorCode)
        assertEquals(
            "ENGINE_POLICY_ALGORITHM_UNSUPPORTED",
            facade.engineFailureFor(ReaderSafetyRuleId.PDF_DISABLE_ACTIVE_CONTENT).errorCode,
        )
    }

    @Test
    fun archiveCoreFactsMapToGeneratedComicRules() {
        assertEquals(
            facade.failureFor(ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE),
            readerSafetyComicArchiveDetectorFailure("ARCHIVE_ENCRYPTED"),
        )
        assertEquals(
            facade.failureFor(ReaderSafetyRuleId.COMIC_PAGE_MAX_COUNT),
            readerSafetyComicArchiveDetectorFailure("ARCHIVE_PAGE_COUNT_EXCEEDED"),
        )
        assertEquals(
            facade.failureFor(ReaderSafetyRuleId.COMIC_ARCHIVE_BUDGET),
            readerSafetyComicArchiveDetectorFailure("ARCHIVE_COMPRESSION_RATIO_EXCEEDED"),
        )
        assertNull(readerSafetyComicArchiveDetectorFailure("ARCHIVE_OPEN_FAILED"))
    }
}
