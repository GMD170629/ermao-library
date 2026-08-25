package com.ermao.library.shared.modules.library

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ContentModelsTest {
    @Test
    fun queryFingerprintDoesNotIncludePage() {
        val first = BooksQuery(
            query = "  三体  ",
            filters = LibraryFilters(readingStatus = ReadingStatus.Reading),
            page = 1,
        )
        val second = first.copy(
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
    fun swiftFriendlyFilterFactoryProducesSingleReadingStatus() {
        val filters = createLibraryFilters(readingStatus = ReadingStatus.Reading)

        assertEquals(ReadingStatus.Reading, filters.readingStatus)
    }
}
