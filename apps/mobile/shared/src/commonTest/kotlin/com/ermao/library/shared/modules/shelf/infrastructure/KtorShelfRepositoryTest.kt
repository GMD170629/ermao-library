package com.ermao.library.shared.modules.shelf.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.shelf.createShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfMembership
import com.ermao.library.shared.modules.shelf.domain.ShelfMembershipChange
import com.ermao.library.shared.modules.shelf.domain.ShelfResult
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.OutgoingContent
import io.ktor.http.headersOf
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json

class KtorShelfRepositoryTest {
    @Test
    fun loadsAllShelfKindsAndResolvesMembershipFromDetail() = runBlocking {
        val harness = Harness(
            SHELVES,
            STATIC_DETAIL,
            SMART_DETAIL,
        )

        val result = assertIs<ShelfResult.Content<*>>(
            harness.repository.loadShelves(context(), "book-1"),
        ).value as List<*>
        val shelf = assertIs<com.ermao.library.shared.modules.shelf.domain.ShelfSummary>(result.first())

        assertEquals("Favorites", shelf.name)
        assertEquals(true, shelf.containsBook)
        assertEquals(listOf("Favorites", "Smart", "Collection"), result.filterIsInstance<com.ermao.library.shared.modules.shelf.domain.ShelfSummary>().map { it.name })
        assertEquals(
            listOf("/base/api/shelves", "/base/api/shelves/shelf-1", "/base/api/shelves/smart-1"),
            harness.requests.map(Request::path),
        )
        val collection = result.filterIsInstance<com.ermao.library.shared.modules.shelf.domain.ShelfSummary>().last()
        assertEquals(false, collection.containsBook)
    }

    @Test
    fun updateUsesEstablishedBulkMembershipContract() = runBlocking {
        val harness = Harness("""{"ok":true,"data":{"updated":1,"changedValues":1,"operation":{"id":"op-1"}}}""")

        assertIs<ShelfResult.Content<*>>(
            harness.repository.updateMembership(
                context(),
                ShelfMembershipChange("book-1", "shelf-1", com.ermao.library.shared.modules.shelf.domain.ShelfKind.Static, ShelfMembership.Add),
            ),
        )

        val request = harness.requests.single()
        assertEquals(HttpMethod.Post, request.method)
        assertEquals("/base/api/library/operations/books/shelf-membership", request.path)
        assertEquals(
            """{"ids":["book-1"],"shelfId":"shelf-1","membership":"ADD"}""",
            request.body,
        )
    }

    private fun context() = createShelfRequestContext(
        profileId = "profile-1",
        displayName = "Books",
        baseUrl = "https://books.example/base",
        serverIdentity = "server-fixture",
        acceptsInsecureTls = false,
        userId = "user-1",
        authorizationVersion = 7,
    )

    private class Harness(vararg responses: String) {
        val requests = mutableListOf<Request>()
        private val pending = ArrayDeque(responses.toList())
        val repository = KtorShelfRepository { profile ->
            ApiClient(
                profile,
                HttpClient(MockEngine { request ->
                    requests += Request(
                        request.method,
                        request.url.encodedPath,
                        (request.body as? OutgoingContent.ByteArrayContent)?.bytes()?.decodeToString().orEmpty(),
                    )
                    respond(
                        pending.removeFirst(),
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                }),
                Json { ignoreUnknownKeys = false; explicitNulls = false },
            )
        }
    }

    private data class Request(val method: HttpMethod, val path: String, val body: String)

    private companion object {
        const val SHELVES = """{"ok":true,"data":{"shelves":[{"id":"shelf-1","name":"Favorites","kind":"STATIC"},{"id":"smart-1","name":"Smart","kind":"SMART"},{"id":"collection-1","name":"Collection","kind":"COLLECTION"}]}}"""
        const val STATIC_DETAIL = """{"ok":true,"data":{"shelf":{"id":"shelf-1","name":"Favorites","kind":"STATIC","bookIds":["book-1"]}}}"""
        const val SMART_DETAIL = """{"ok":true,"data":{"shelf":{"id":"smart-1","name":"Smart","kind":"SMART","bookIds":[]}}}"""
    }
}
