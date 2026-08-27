package com.ermao.library.shared.modules.shelf

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.shelf.domain.ShelfResult
import com.ermao.library.shared.modules.shelf.infrastructure.KtorShelfCatalogRepository
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.OutgoingContent
import io.ktor.http.headersOf
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs

class ShelfCatalogTest {
    @Test fun scopesIncludeGroupedShelvesAndSearchAllSummaries() {
        val entries = listOf(entry("c", ShelfKind.Collection), entry("s", ShelfKind.Static, listOf("c")), entry("t", ShelfKind.Smart))
        assertEquals(listOf("c", "s", "t"), catalogEntries(entries, ShelfCatalogScope.All, "").map { it.id })
        assertEquals(listOf("s", "t"), catalogEntries(entries, ShelfCatalogScope.Shelves, "").map { it.id })
        assertEquals(listOf("c"), catalogEntries(entries, ShelfCatalogScope.Collections, "").map { it.id })
        assertEquals(listOf("s"), catalogEntries(entries, ShelfCatalogScope.All, " S ", "c").map { it.id })
        assertEquals(emptyList(), catalogEntries(entries, ShelfCatalogScope.Collections, "missing"))
    }

    @Test fun collectionArtworkUsesUniqueMemberBooksOnly() {
        val collection = entry("c", ShelfKind.Collection)
        val entries = listOf(collection,
            entry("s", ShelfKind.Static, listOf("c"), listOf(book("a"), book("b"))),
            entry("t", ShelfKind.Smart, listOf("c"), listOf(book("a"), book("c"), book("d"))),
            entry("other", ShelfKind.Static, books = listOf(book("private"))))
        assertEquals(listOf("a", "b", "c"), catalogPreview(collection, entries).map { it.id })
        assertEquals(emptyList(), catalogPreview(entry("empty", ShelfKind.Collection), entries))
    }

    @Test fun createRejectsSmartAndInvalidMembership() {
        assertFailsWith<IllegalArgumentException> { CreateShelfInput(" ", "", ShelfKind.Static, emptyList()) }
        assertFailsWith<IllegalArgumentException> { CreateShelfInput("smart", "", ShelfKind.Smart, emptyList()) }
        assertFailsWith<IllegalArgumentException> { CreateShelfInput("s", "", ShelfKind.Static, listOf("x")) }
        assertFailsWith<IllegalArgumentException> { CreateShelfInput("c", "", ShelfKind.Collection, listOf("s", "s")) }
    }

    @Test fun catalogDecodesRealCollectionAndSummaryWithoutNPlusOne() = runBlocking {
        var requests = 0
        val repository = repository("""{"ok":true,"data":{"shelves":[$STATIC,$COLLECTION]}}""") { requests++ }
        val entries = assertIs<ShelfResult.Content<List<ShelfCatalogEntry>>>(repository.loadCatalog(context())).value
        assertEquals(2, entries.size)
        assertEquals("b1", entries.first().books.single().id)
        assertEquals(ShelfKind.Collection, entries.last().kind)
        assertEquals(1, requests)
    }

    @Test fun malformedItemFailsWholeResponseRatherThanSilentlyDroppingIt() = runBlocking {
        val repository = repository("""{"ok":true,"data":{"shelves":[$STATIC,{"id":"broken","kind":"STATIC"}]}}""")
        assertIs<ShelfResult.Failure>(repository.loadCatalog(context()))
        Unit
    }

    @Test fun paginatedDetailUsesEstablishedBoundedContract() = runBlocking {
        val repository = repository("""{"ok":true,"data":{"shelf":${STATIC.dropLast(1)},"page":2,"totalPages":3}}}""") { request ->
            assertEquals("/base/api/shelves/s1", request.url.encodedPath)
            assertEquals("2", request.url.parameters["page"])
            assertEquals("24", request.url.parameters["pageSize"])
            assertEquals("false", request.url.parameters["includeBookIds"])
        }
        val page = assertIs<ShelfResult.Content<ShelfCatalogPage>>(repository.loadPage(context(), "s1", 2)).value
        assertEquals(2, page.page)
        assertEquals(3, page.totalPages)
    }

    @Test fun createCollectionSendsOnlyShelfMembershipNeverBookIds() = runBlocking {
        val repository = repository("""{"ok":true,"data":{"shelf":{"id":"created"}}}""") { request ->
            val body = (request.body as OutgoingContent.ByteArrayContent).bytes().decodeToString()
            assertEquals("""{"name":"Plan","description":"","kind":"COLLECTION","memberShelfIds":["s1"]}""", body)
        }
        assertEquals("created", assertIs<ShelfResult.Content<String>>(repository.createShelf(context(), CreateShelfInput(" Plan ", "", ShelfKind.Collection, listOf("s1")))).value)
    }

    @Test fun authorizationFailureRemainsDistinct() = runBlocking {
        val repository = repository("""{"ok":false,"error":{"code":"AUTH_REQUIRED","message":"Sign in"}}""", status = HttpStatusCode.Unauthorized)
        val error = assertIs<ShelfResult.Failure>(repository.loadCatalog(context())).error
        assertEquals(ShelfErrorKind.Unauthorized, error.kind)
    }

    private fun context() = createShelfRequestContext("p", "Books", "https://books.example/base", "server", false, "user", 1)
    private fun repository(response: String, status: HttpStatusCode = HttpStatusCode.OK, inspect: (io.ktor.client.request.HttpRequestData) -> Unit = {}) =
        KtorShelfCatalogRepository { profile -> ApiClient(profile, HttpClient(MockEngine { request ->
            inspect(request)
            respond(response, status, headersOf(HttpHeaders.ContentType, "application/json"))
        }), Json { ignoreUnknownKeys = true }) }

    private fun entry(id: String, kind: ShelfKind, collections: List<String> = emptyList(), books: List<ShelfBookPreview> = emptyList()) =
        ShelfCatalogEntry(id, id, null, kind, books.size, books, collections, true)
    private fun book(id: String) = ShelfBookPreview(id, id, null, "/api/books/$id/cover", 0.0)

    private companion object {
        const val STATIC = """{"id":"s1","name":"Shelf","description":null,"kind":"STATIC","bookCount":1,"books":[{"id":"b1","title":"Book","author":null,"coverUrl":"/api/books/b1/cover?size=medium","progress":12.5}],"collectionIds":["c1"],"rulesStatus":"VALID"}"""
        const val COLLECTION = """{"id":"c1","name":"Plan","kind":"COLLECTION","shelfCount":1,"shelves":[],"rulesStatus":"VALID"}"""
    }
}
