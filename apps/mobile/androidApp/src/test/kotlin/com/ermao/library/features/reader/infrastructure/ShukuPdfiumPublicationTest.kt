package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderPdfPage
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ShukuPdfiumPublicationTest {
    @Test
    fun mapsCanonicalZeroBasedPagesToOneBasedReadiumPositions() {
        val positions = createCanonicalPdfPositionSpecs(
            listOf(
                ReaderPdfPage(0, "Cover"),
                ReaderPdfPage(1, "Chapter"),
                ReaderPdfPage(2, "Back"),
            ),
        )

        assertEquals(listOf(1, 2, 3), positions.map(CanonicalPdfPositionSpec::position))
        assertEquals(listOf(0.0, 0.5, 1.0), positions.map(CanonicalPdfPositionSpec::totalProgression))
    }

    @Test
    fun rejectsNonContiguousCanonicalPageIndices() {
        assertFailsWith<IllegalArgumentException> {
            createCanonicalPdfPositionSpecs(
                listOf(ReaderPdfPage(0, "First"), ReaderPdfPage(2, "Third")),
            )
        }
    }
}
