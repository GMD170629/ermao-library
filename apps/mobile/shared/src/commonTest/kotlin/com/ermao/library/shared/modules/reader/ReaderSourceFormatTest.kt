package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
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
        assertEquals(ReaderFormat.Epub, ReaderSourceFormat.Fb2.readerFormat)
        assertEquals(ReaderFormat.Text, ReaderSourceFormat.Txt.readerFormat)
        assertEquals(ReaderFormat.Comic, ReaderSourceFormat.Cbz.readerFormat)
        assertEquals(ReaderFormat.Comic, ReaderSourceFormat.ImageDir.readerFormat)
        assertEquals(ReaderFormat.Pdf, ReaderSourceFormat.Pdf.readerFormat)
        assertEquals(ReaderFormat.Audio, ReaderSourceFormat.AudiobookDir.readerFormat)
    }

    @Test
    fun sourceFormatOwnsItsMimePolicyAndMustMatchTheReaderFormat() {
        assertTrue(ReaderSourceFormat.Epub.acceptsMimeType("application/epub+zip"))
        assertTrue(ReaderSourceFormat.Fb2.acceptsMimeType("application/x-fictionbook+xml"))
        assertTrue(ReaderSourceFormat.Azw3.acceptsMimeType("application/vnd.amazon.ebook"))
        assertTrue(ReaderSourceFormat.Txt.acceptsMimeType("text/plain"))
        assertTrue(ReaderSourceFormat.Cbz.acceptsMimeType("application/vnd.comicbook+zip"))
        assertTrue(ReaderSourceFormat.Pdf.acceptsMimeType("application/pdf"))
        assertTrue(ReaderSourceFormat.Audio.acceptsMimeType("audio/mpeg"))
        assertTrue(ReaderSourceFormat.AudiobookDir.acceptsMimeType("audio/mp4"))
        assertFalse(ReaderSourceFormat.Audio.acceptsMimeType("audio/x-unknown"))
        assertFalse(ReaderSourceFormat.Audio.acceptsMimeType("application/octet-stream"))
        assertFailsWith<IllegalArgumentException> {
            LocalReaderSource(
                resourceId = "resource-1",
                displayTitle = "Book",
                format = ReaderFormat.Epub,
                sourceFormat = ReaderSourceFormat.Azw3,
            )
        }
    }
}
