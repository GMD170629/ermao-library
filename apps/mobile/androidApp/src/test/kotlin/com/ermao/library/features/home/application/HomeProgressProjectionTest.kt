package com.ermao.library.features.home.application

import com.ermao.library.features.content.model.ContinueReadingCard
import com.ermao.library.features.content.model.HomeContent
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.shared.modules.reader.ComicPublicationLocation
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import kotlin.test.assertEquals
import org.junit.Test

class HomeProgressProjectionTest {
    @Test
    fun matchingReaderProgressImmediatelyUpdatesContinueReadingAndRelatedCards() {
        val work = WorkCard("work-1", "Title", "Author", "", listOf("COMIC"), 75)
        val home = HomeContent(
            continueReading = ContinueReadingCard(
                work = work,
                volumeTitle = "Volume",
                positionLabel = null,
                lastReadAtEpochMillis = null,
                resumeVolumeId = "volume-1",
            ),
            recentReading = listOf(work),
            recentAdded = listOf(work),
        )
        val update = ReaderProgressPresentationUpdate(
            namespaceKey = "server|user|1",
            workId = work.id,
            volumeId = "volume-1",
            percent = 100.0,
            location = ComicPublicationLocation("pages/100.jpg", 99),
            chapterTitle = null,
            capturedAtEpochMillis = 1,
        )

        val updated = home.applying(update)

        assertEquals(100, updated.continueReading?.work?.progressPercent)
        assertEquals(100, updated.recentReading.single().progressPercent)
        assertEquals(100, updated.recentAdded.single().progressPercent)
        assertEquals(home, home.applying(update.copy(volumeId = "another-volume")))
    }
}
