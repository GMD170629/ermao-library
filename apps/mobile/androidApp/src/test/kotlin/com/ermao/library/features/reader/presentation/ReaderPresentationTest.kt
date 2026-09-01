package com.ermao.library.features.reader.presentation

import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import kotlin.test.assertEquals
import kotlin.test.assertNull
import org.junit.Test

class ReaderPresentationTest {
    @Test
    fun progressScrubberTracksEveryReaderMorphology() {
        assertEquals(
            0.7,
            readerTotalProgression(
                ReflowReaderLocation(progression = 0.4, totalProgression = 0.7),
                lastPageIndex = 0,
            ),
        )
        assertEquals(
            0.5,
            readerTotalProgression(ComicReaderLocation("page-2.jpg", 1), lastPageIndex = 2),
        )
        assertEquals(
            0.5,
            readerTotalProgression(
                ComicReaderLocation("page-1.jpg", 0),
                lastPageIndex = 2,
                presentationProgress = 0.5,
            ),
            "Double-page comics report the last visible logical page while keeping the exact locator",
        )
        assertEquals(
            0.75,
            readerTotalProgression(PdfReaderLocation(3, 0.0), lastPageIndex = 4),
        )
        assertEquals(
            1.0,
            readerTotalProgression(PdfReaderLocation(0, 0.0), lastPageIndex = 0),
        )
        assertNull(
            readerTotalProgression(ReflowReaderLocation(progression = 0.4), lastPageIndex = 0),
            "Chapter progression must never be presented as whole-publication progress",
        )
    }
}
