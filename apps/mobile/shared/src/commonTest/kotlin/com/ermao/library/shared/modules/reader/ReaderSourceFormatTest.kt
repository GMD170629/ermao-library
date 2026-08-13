package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class ReaderSourceFormatTest {
    @Test
    fun mobiFamilyRetainsItsContainerFormatWhileSharingOneReaderFormat() {
        listOf(
            ReaderSourceFormat.Mobi,
            ReaderSourceFormat.Azw,
            ReaderSourceFormat.Azw3,
            ReaderSourceFormat.Prc,
        ).forEach { sourceFormat ->
            assertEquals(ReaderFormat.Mobi, sourceFormat.readerFormat)
            assertEquals(sourceFormat, ReaderSourceFormat.fromWireValue(sourceFormat.wireValue.uppercase()))
        }
        assertEquals(ReaderFormat.Epub, ReaderSourceFormat.Epub.readerFormat)
        assertEquals(ReaderFormat.Text, ReaderSourceFormat.Txt.readerFormat)
        assertEquals(ReaderFormat.Comic, ReaderSourceFormat.Cbz.readerFormat)
        assertEquals(ReaderFormat.Pdf, ReaderSourceFormat.Pdf.readerFormat)
    }

    @Test
    fun sourceFormatOwnsItsMimePolicyAndMustMatchTheReaderFormat() {
        assertTrue(ReaderSourceFormat.Epub.acceptsMimeType("application/epub+zip"))
        assertTrue(ReaderSourceFormat.Azw3.acceptsMimeType("application/vnd.amazon.ebook"))
        assertTrue(ReaderSourceFormat.Txt.acceptsMimeType("text/plain"))
        assertTrue(ReaderSourceFormat.Cbz.acceptsMimeType("application/vnd.comicbook+zip"))
        assertTrue(ReaderSourceFormat.Pdf.acceptsMimeType("application/pdf"))
        assertFailsWith<IllegalArgumentException> {
            LocalReaderSource(
                sourceId = "volume-1",
                displayTitle = "Book",
                format = ReaderFormat.Epub,
                contentFingerprint = fingerprint(),
                sourceFormat = ReaderSourceFormat.Azw3,
            )
        }
    }

    private fun fingerprint() = ContentFingerprint(
        originalFileHash = "sha256:${"a".repeat(64)}",
        parserVersion = "parser-v1",
        normalizationVersion = "normalization-v1",
    )
}
