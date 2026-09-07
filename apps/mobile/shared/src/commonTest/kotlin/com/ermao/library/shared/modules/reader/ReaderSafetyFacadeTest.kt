package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyMarkupResult
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
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
    fun literalizesExternalEntityWithoutRejectingReadableMarkup() {
        val accepted = assertIs<ReaderSafetyMarkupResult.Accepted>(facade.sanitizeMarkup(
            "<!DOCTYPE book [<!ENTITY x SYSTEM \"file:///tmp/secret\">]><html><head></head><body>&x;</body></html>",
        ))

        assertTrue(accepted.value.changed)
        assertFalse(accepted.value.markup.contains("<!DOCTYPE"))
        assertTrue(accepted.value.parserMarkup.contains("&#38;x;"))
    }

    @Test
    fun acceptsArbitraryDoctypeAndExpandsBoundedPlainTextEntityAsText() {
        val accepted = assertIs<ReaderSafetyMarkupResult.Accepted>(facade.sanitizeMarkup(
            """<!DOCTYPE novel [<!ENTITY title "A <b>safe</b> title">]><html><head></head><body>&title;</body></html>""",
        ))

        assertFalse(accepted.value.markup.contains("<!DOCTYPE"))
        assertTrue(accepted.value.markup.contains("&lt;b&gt;safe&lt;/b&gt;"))
        assertFalse(accepted.value.parserMarkup.contains("<b>safe</b>"))
    }

    @Test
    fun literalizesUnknownAndCyclicEntitiesAndLeavesCommentsAndCdataUntouched() {
        val accepted = assertIs<ReaderSafetyMarkupResult.Accepted>(facade.sanitizeMarkup(
            """<!DOCTYPE novel [<!ENTITY a "&b;"><!ENTITY b "&a;">]><html><head></head><body><!-- &unknown; --><![CDATA[&unknown;]]>&unknown;&a;</body></html>""",
        ))

        assertTrue(accepted.value.markup.contains("<!-- &unknown; -->"))
        assertTrue(accepted.value.markup.contains("<![CDATA[&unknown;]]>"))
        assertTrue(accepted.value.parserMarkup.contains("&#38;unknown;"))
        assertTrue(accepted.value.parserMarkup.contains("&#38;a;"))
    }

    @Test
    fun repeatedEntityReferencesStayBoundedAndPreserveTheClosingTags() {
        val source = "<!DOCTYPE novel [<!ENTITY title \"Readable title\">]>" +
            "<html><body>" + "&title;".repeat(50_000) + "</body></html>"

        val accepted = assertIs<ReaderSafetyMarkupResult.Accepted>(facade.prepareXmlMarkup(source))
        val outputBytes = accepted.value.markup.encodeToByteArray().size.toLong()
        val sourceBytes = source.encodeToByteArray().size.toLong()
        val maximumBytes = ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.REFLOWABLE_MARKUP_MAX_BYTES)

        assertTrue(accepted.value.markup.endsWith("</body></html>"))
        assertTrue(outputBytes <= sourceBytes + maximumBytes)
    }

    @Test
    fun noSemicolonAmpersandsAreEscapedWithoutDroppingTheDocumentTail() {
        val source = "<html><body>" + "&".repeat(100_000) + "</body></html>"

        val accepted = assertIs<ReaderSafetyMarkupResult.Accepted>(facade.prepareXmlMarkup(source))

        assertTrue(accepted.value.markup.contains("&amp;"))
        assertTrue(accepted.value.parserMarkup.contains("&#38;"))
        assertTrue(accepted.value.markup.endsWith("</body></html>"))
    }

    @Test
    fun extractsContainerRootfileReferencesAfterSafePreparation() {
        val source = """
            <!DOCTYPE container [
              <!-- <rootfile full-path="fake/comment.opf"/> -->
              <!ENTITY ignored "<rootfile full-path='fake/entity.opf'/>">
            ]>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <!-- <rootfile full-path="fake/nav.opf"/> -->
                <rootfile full-path="OPS/package&amp;one&#x2E;opf" media-type="application/oebps-package+xml"/>
              </rootfiles>
            </container>
        """.trimIndent()

        assertEquals(
            listOf("OPS/package&one.opf"),
            facade.requireContainerRootFilePaths(source),
        )
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
    fun authoredNavigationBridgeKeepsUnknownSchemesAndRejectsOnlyGeneratedBlacklist() {
        assertTrue(readerAllowsAuthoredUserNavigation("future-reader:chapter"))
        assertFalse(readerAllowsAuthoredUserNavigation("javascript:alert(1)"))
        assertFalse(readerAllowsAuthoredUserNavigation("file:///tmp/book"))
        assertFalse(readerAllowsAuthoredUserNavigation("data:text/plain,book"))
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
            readerSafetyComicArchiveDetectorFailure("ARCHIVE_PATH_INVALID"),
        )
        assertEquals(
            facade.failureFor(ReaderSafetyRuleId.COMIC_PAGE_MAX_COUNT),
            readerSafetyComicArchiveDetectorFailure("ARCHIVE_PAGE_COUNT_EXCEEDED"),
        )
        assertEquals(
            facade.failureFor(ReaderSafetyRuleId.COMIC_ARCHIVE_BUDGET),
            readerSafetyComicArchiveDetectorFailure("ARCHIVE_COMPRESSION_RATIO_EXCEEDED"),
        )
        assertEquals(
            facade.failureFor(ReaderSafetyRuleId.COMIC_PAGE_MAX_BYTES),
            readerSafetyComicArchiveDetectorFailure("ARCHIVE_PAGE_LIMIT_EXCEEDED"),
        )
        assertNull(readerSafetyComicArchiveDetectorFailure("ARCHIVE_OPEN_FAILED"))
    }

    @Test
    fun archiveEncryptionAndDamagedBytesAreNotSecurityFindings() {
        assertEquals(
            facade.failureFor(ReaderSafetyRuleId.COMIC_PAGE_MIME),
            readerSafetyComicArchiveDetectorFailure("ARCHIVE_ENCRYPTED"),
        )
        listOf("ARCHIVE_PATH_DUPLICATE", "ARCHIVE_HEADER_INVALID", "ARCHIVE_DATA_INVALID", "ARCHIVE_DATA_TRUNCATED")
            .forEach { code ->
                val failure = readerSafetyComicArchiveDetectorFailure(code)
                assertEquals(facade.failureFor(ReaderSafetyRuleId.COMIC_RESOURCE_INTEGRITY), failure, code)
                assertEquals(
                    ReaderErrorCode.ComicArchiveCorrupt,
                    readerErrorCodeForFailure(requireNotNull(failure).errorCode, recoverable = false),
                    code,
                )
            }
    }
}
