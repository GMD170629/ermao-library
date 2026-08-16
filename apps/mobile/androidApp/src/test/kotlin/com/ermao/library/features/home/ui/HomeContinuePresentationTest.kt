package com.ermao.library.features.home.ui

import java.time.Instant
import java.time.ZoneId
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import org.junit.Test

class HomeContinuePresentationTest {
    @Test
    fun largeTextReducesHomeShelvesToTwoReadableColumns() {
        assertEquals(3, homeShelfColumnCount(compactColumns = 3, fontScale = 1.29f))
        assertEquals(2, homeShelfColumnCount(compactColumns = 3, fontScale = 1.3f))
        assertEquals(2, homeShelfColumnCount(compactColumns = 3, fontScale = 2f))
    }

    @Test
    fun positionTakesPriorityAndAnEquivalentVolumeTitleIsNotRepeated() {
        assertEquals(
            "Chapter 12",
            selectContinuePositionLabel(
                workTitle = "A Very Long Work Title",
                positionLabel = " Chapter 12 ",
                volumeTitle = "Volume 2",
            ),
        )
        assertNull(
            selectContinuePositionLabel(
                workTitle = "A Very Long Work Title",
                positionLabel = null,
                volumeTitle = "  A Very Long Work Title  ",
            ),
        )
        assertEquals(
            "Volume 2",
            selectContinuePositionLabel(
                workTitle = "A Very Long Work Title",
                positionLabel = null,
                volumeTitle = "Volume 2",
            ),
        )
        assertEquals(
            "01",
            selectContinuePositionLabel(
                workTitle = "A Very Long Work Title",
                positionLabel = "A Very Long Work Title 01",
                volumeTitle = null,
            ),
        )
        assertNull(
            selectContinuePositionLabel(
                workTitle = "A Very Long Work Title",
                positionLabel = " A Very Long Work Title ",
                volumeTitle = null,
            ),
        )
    }

    @Test
    fun mappedInstantBecomesRelativeTimeWithoutLeakingWireText() {
        val presentation = homeLastReadPresentation(
            lastReadAtEpochMillis = Instant.parse("2026-08-15T13:47:38.286000Z").toEpochMilli(),
            now = Instant.parse("2026-08-15T14:00:00Z"),
            zoneId = ZoneId.of("Asia/Shanghai"),
        )

        val today = assertIs<HomeLastReadPresentation.Today>(presentation)
        assertEquals(Instant.parse("2026-08-15T13:47:38.286000Z"), today.instant)
    }

    @Test
    fun olderTimestampUsesAbsolutePresentationAndMissingInputIsHidden() {
        val presentation = homeLastReadPresentation(
            lastReadAtEpochMillis = Instant.parse("2026-08-13T13:47:38Z").toEpochMilli(),
            now = Instant.parse("2026-08-15T14:00:00Z"),
            zoneId = ZoneId.of("Asia/Shanghai"),
        )

        val absolute = assertIs<HomeLastReadPresentation.Absolute>(presentation)
        assertEquals(Instant.parse("2026-08-13T13:47:38Z"), absolute.instant)
        assertNull(
            homeLastReadPresentation(
                lastReadAtEpochMillis = null,
                now = Instant.parse("2026-08-15T14:00:00Z"),
                zoneId = ZoneId.of("Asia/Shanghai"),
            ),
        )
    }

    @Test
    fun dayClassificationUsesTheInjectedZoneAtTheMidnightBoundary() {
        val lastReadAt = Instant.parse("2026-08-14T23:30:00Z").toEpochMilli()
        val now = Instant.parse("2026-08-15T00:30:00Z")

        assertIs<HomeLastReadPresentation.Yesterday>(
            homeLastReadPresentation(
                lastReadAtEpochMillis = lastReadAt,
                now = now,
                zoneId = ZoneId.of("UTC"),
            ),
        )
        assertIs<HomeLastReadPresentation.Today>(
            homeLastReadPresentation(
                lastReadAtEpochMillis = lastReadAt,
                now = now,
                zoneId = ZoneId.of("Asia/Shanghai"),
            ),
        )
    }
}
