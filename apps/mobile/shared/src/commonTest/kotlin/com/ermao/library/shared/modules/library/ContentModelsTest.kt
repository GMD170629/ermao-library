package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.library.domain.MediaKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ContentModelsTest {
    @Test
    fun queryFingerprintIsStableAcrossFilterInsertionOrderAndDoesNotIncludePage() {
        val first = BooksQuery(
            query = "  三体  ",
            filters = LibraryFilters(
                linkedSetOf(MediaKind.Comic, MediaKind.Ebook),
                linkedSetOf(ReadingStatus.Reading, ReadingStatus.Finished),
            ),
            page = 1,
        )
        val second = first.copy(
            filters = LibraryFilters(
                linkedSetOf(MediaKind.Ebook, MediaKind.Comic),
                linkedSetOf(ReadingStatus.Finished, ReadingStatus.Reading),
            ),
            page = 3,
        )

        assertEquals(first.fingerprint(), second.fingerprint())
    }

    @Test
    fun downloadedOnlyParticipatesInTheQueryIdentity() {
        val query = BooksQuery()

        assertTrue(query.fingerprint() != query.copy(filters = LibraryFilters(downloadedOnly = true)).fingerprint())
    }

    @Test
    fun facetSortDefaultsAreFixedByFacetKind() {
        assertEquals(
            FacetSort.SeriesIndex,
            FacetQuery(com.ermao.library.shared.modules.library.domain.FacetKind.Series, "series-1").sort,
        )
        assertEquals(
            FacetSort.RecentlyRead,
            FacetQuery(com.ermao.library.shared.modules.library.domain.FacetKind.Author, "author-1").sort,
        )
    }

    @Test
    fun swiftFriendlyFilterFactoryProducesTypedMediaKinds() {
        val filters = createLibraryFilters(
            mediaKindWireValues = listOf("COMIC", "AUDIOBOOK"),
            readingStatuses = setOf(ReadingStatus.Reading),
        )

        assertEquals(setOf(MediaKind.Comic, MediaKind.Audiobook), filters.mediaKinds)
        assertTrue(ReadingStatus.Reading in filters.readingStatuses)
    }
}
