package com.ermao.library.features.home.application

import com.ermao.library.features.content.model.ContinueReadingCard
import com.ermao.library.features.content.model.HomeContent
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import com.ermao.library.shared.modules.reader.ReaderPagePresentation
import com.ermao.library.shared.modules.reader.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionReport
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import kotlin.test.assertEquals
import org.junit.Test

class HomeProgressProjectionTest {
    @Test
    fun matchingReaderProgressImmediatelyUpdatesContinueReadingAndRelatedCards() {
        val book = BookCard("book-1", "Title", "Author", "", 75)
        val home = HomeContent(
            continueReading = ContinueReadingCard(
                book = book,
                resourceTitle = "Resource",
                positionLabel = null,
                lastReadAtEpochMillis = null,
                resumeResourceId = "resource-1",
            ),
            recentReading = listOf(book),
            recentAdded = listOf(book),
        )
        val update = ReaderProgressPresentationUpdate(
            namespaceKey = "server|user|1",
            bookId = book.id,
            resourceId = "resource-1",
            position = ReaderPositionReport(
                locator = ReaderOpaqueLocator.parse("""{"href":"pages/100.jpg"}"""),
                presentation = ReaderPositionPresentation(
                    displayPercent = 100.0,
                    totalProgression = 1.0,
                    currentHref = "pages/100.jpg",
                    chapter = null,
                    page = ReaderPagePresentation(number = 100, total = 100),
                    playback = null,
                ),
            ),
            capturedAtEpochMillis = 1,
        )

        val updated = home.applying(update)

        assertEquals(100, updated.continueReading?.book?.progressPercent)
        assertEquals(100, updated.recentReading.single().progressPercent)
        assertEquals(100, updated.recentAdded.single().progressPercent)
        assertEquals(home, home.applying(update.copy(resourceId = "another-resource")))
    }
}
