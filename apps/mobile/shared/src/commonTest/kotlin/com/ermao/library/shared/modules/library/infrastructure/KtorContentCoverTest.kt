package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.workmanagement.createWorkManagementContext
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class KtorContentCoverTest {
    @Test fun coverRequestsUseSmallVariantAndKeepBasePathAndValidators() = runBlocking {
        val management = createWorkManagementContext("profile", "Test", "https://library.example/base", "server", false, "user", 1)
        val context = ContentRequestContext(management.profile, management.namespace)
        val requests = mutableListOf<String>()
        val repository = KtorContentRepository { profile ->
            ApiClient(profile, HttpClient(MockEngine { request ->
                requests += request.url.toString()
                assertEquals("GET", request.method.value)
                assertEquals("cover-etag", request.headers[HttpHeaders.IfNoneMatch])
                respond(byteArrayOf(1, 2, 3), HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "image/png"))
            }), Json { ignoreUnknownKeys = false })
        }
        assertIs<ContentResult.Content<*>>(repository.loadCover(context, "/api/books/book/cover?size=medium&v=9", "cover-etag"))
        assertIs<ContentResult.Content<*>>(repository.loadCover(context, "/api/resources/book/previews/1?size=large", "cover-etag"))
        assertEquals(listOf("https://library.example/base/api/books/book/cover?v=9&size=small",
            "https://library.example/base/api/resources/book/previews/1?size=large"), requests)
    }
}
