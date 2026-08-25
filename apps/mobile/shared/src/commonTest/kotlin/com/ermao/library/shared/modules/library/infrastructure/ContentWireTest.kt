package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiEnvelopeDecoder
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.modules.library.domain.FacetKind
import com.ermao.library.shared.modules.library.BooksQuery
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertNotNull
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json

class ContentWireTest {
    private val decoder = ApiEnvelopeDecoder(Json { ignoreUnknownKeys = false; explicitNulls = false })

    @Test
    fun decodesBookFacetPageWithStableIdentity() {
        val result = decoder.decode(
            200,
            """{"ok":true,"data":{"books":[],"page":1,"pageSize":24,"total":0,"totalPages":1,"appliedFacet":{"id":"series-1","kind":"SERIES","name":"Saga"}}}""",
            BookPageWire.serializer(),
        )

        val page = assertNotNull(
            assertIs<ApiResult.Success<BookPageWire>>(result).value.toFacetPage(FacetKind.Series, "series-1"),
        )
        assertEquals("series-1", page.facet.id)
        assertEquals(FacetKind.Series, page.facet.kind)
    }

    @Test
    fun missingFacetIdentityFallsBackToRequestedBookFacet() {
        val result = decoder.decode(
            200,
            """{"ok":true,"data":{"books":[],"page":1,"pageSize":24,"total":0,"totalPages":1,"appliedFacet":null}}""",
            BookPageWire.serializer(),
        )

        val page = assertIs<ApiResult.Success<BookPageWire>>(result).value
            .toFacetPage(FacetKind.Author, "author-1")
        assertEquals("author-1", page.facet.id)
        assertEquals(FacetKind.Author, page.facet.kind)
        assertEquals("author-1", page.facet.name)
    }

    @Test
    fun groupingRepresentativeBooksAreBounded() {
        val result = decoder.decode(
            200,
            """{"ok":true,"data":{"groups":[{"id":"author-1","name":"Ursula","bookCount":4,"updatedAt":"2026-01-01T00:00:00Z","representativeBooks":[${representativeBook("1")},${representativeBook("2")},${representativeBook("3")},${representativeBook("4")}]}],"page":1,"pageSize":30,"total":1,"totalPages":1}}""",
            GroupingPageWire.serializer(),
        )

        val group = assertIs<ApiResult.Success<GroupingPageWire>>(result).value.toPage().items.single()
        assertEquals(listOf("1", "2", "3"), group.representativeBooks.map { it.id })
    }

    @Test
    fun decodesCurrentContinueReadingBookResourceContract() {
        val result = decoder.decode(
            200,
            """{"ok":true,"data":{"item":{"bookId":"book-1","title":"Title","author":null,"coverUrl":"/api/books/book-1/cover","resourceFormat":"EPUB","readerType":"reflowable","resumeResourceId":"resource-1","progress":42.0,"chapter":null,"lastReadAt":"2026-08-12T00:00:00Z","resourceTitle":"Resource 1","narrator":null}}}""",
            ContinueReadingPayloadWire.serializer(),
        )

        val item = assertIs<ApiResult.Success<ContinueReadingPayloadWire>>(result).value.item
        assertEquals("book-1", item?.toDomain()?.bookId)
        assertEquals("EPUB", item?.resourceFormat)
        assertEquals("resource-1", item?.resumeResourceId)
        assertNull(item?.chapter)
    }

    @Test
    fun selectedLibraryUsesTheSupportedFilterExpression() {
        val allParameters = libraryBooksParameters(BooksQuery())
        assertFalse("filters" in allParameters)
        assertFalse("libraryId" in allParameters)

        val selected = libraryBooksParameters(BooksQuery(libraryId = "library-1"))
        val filter = selected.getValue("filters").single()
        assertTrue(filter.contains("\"field\":\"library\""))
        assertTrue(filter.contains("\"operator\":\"equals\""))
        assertTrue(filter.contains("\"value\":\"library-1\""))
        assertFalse("libraryId" in selected)
    }

    private fun representativeBook(id: String) =
        """{"id":"$id","title":"Title $id","author":null,"coverUrl":"/api/books/$id/cover","updatedAt":"2026-01-01T00:00:00Z"}"""
}
