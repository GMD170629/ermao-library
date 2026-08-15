package com.ermao.library.features.reader.presentation

import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import kotlin.test.assertEquals
import org.junit.Test

class ReaderPresentationTest {
    @Test
    fun progressScrubberTracksEveryReaderMorphology() {
        assertEquals(
            0.4,
            readerTotalProgression(ReflowReaderLocation(progression = 0.4), lastPageIndex = 0),
        )
        assertEquals(
            0.5,
            readerTotalProgression(ComicReaderLocation("page-2.jpg", 1), lastPageIndex = 2),
        )
        assertEquals(
            0.75,
            readerTotalProgression(PdfReaderLocation(3, 0.0), lastPageIndex = 4),
        )
        assertEquals(
            1.0,
            readerTotalProgression(PdfReaderLocation(0, 0.0), lastPageIndex = 0),
        )
    }
}
