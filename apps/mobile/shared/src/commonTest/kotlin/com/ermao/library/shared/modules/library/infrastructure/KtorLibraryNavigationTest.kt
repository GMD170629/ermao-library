package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.LibraryOption
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

class KtorLibraryNavigationTest {
    @Test fun namesUseOneMinimalRequest() = runBlocking {
        val paths = mutableListOf<String>()
        val repository = repository { path ->
            paths += path
            """{"ok":true,"data":{"sources":[{"id":"l1","name":"Library"}]}}""" to HttpStatusCode.OK
        }
        val result = assertIs<ContentResult.Content<List<LibraryOption>>>(repository.loadLibraryOptions(context()))
        assertEquals(listOf(LibraryOption("l1", "Library")), result.value)
        assertEquals(listOf("/base/api/library/navigation-sources"), paths)
    }

    @Test fun oldServerUsesExistingSchemaOnlyWhenNavigationEndpointIsMissing() = runBlocking {
        val paths = mutableListOf<String>()
        val repository = repository { path ->
            paths += path
            if (path.endsWith("navigation-sources")) ERROR to HttpStatusCode.NotFound
            else LEGACY_SCHEMA to HttpStatusCode.OK
        }
        val result = assertIs<ContentResult.Content<List<LibraryOption>>>(repository.loadLibraryOptions(context()))
        assertEquals(listOf(LibraryOption("l1", "Legacy library")), result.value)
        assertEquals(listOf("/base/api/library/navigation-sources", "/base/api/library/filter-schema"), paths)
    }

    @Test fun authorizationAndServerFailuresNeverFallBack() = runBlocking {
        for (status in listOf(HttpStatusCode.Unauthorized, HttpStatusCode.Forbidden, HttpStatusCode.InternalServerError)) {
            val paths = mutableListOf<String>()
            val repository = repository { path -> paths += path; ERROR to status }
            assertIs<ContentResult.Failure>(repository.loadLibraryOptions(context()))
            assertEquals(listOf("/base/api/library/navigation-sources"), paths)
        }
    }

    private fun context(): ContentRequestContext {
        val management = createWorkManagementContext("p", "Test", "https://books.example/base", "server", false, "user", 1)
        return ContentRequestContext(management.profile, management.namespace)
    }

    private fun repository(response: (String) -> Pair<String, HttpStatusCode>) = KtorContentRepository { profile ->
        ApiClient(profile, HttpClient(MockEngine { request ->
            val (body, status) = response(request.url.encodedPath)
            respond(body, status, headersOf(HttpHeaders.ContentType, "application/json"))
        }), Json { ignoreUnknownKeys = false; explicitNulls = false })
    }

    private companion object {
        const val ERROR = """{"ok":false,"error":{"code":"HTTP_ERROR","message":"Unavailable"}}"""
        const val LEGACY_SCHEMA = """{"ok":true,"data":{"fields":[{"key":"library","label":"Library","group":"scope","type":"enum","operators":["equals"],"options":[{"value":"l1","label":"Legacy library"}]}],"maxConditions":12}}"""
    }
}
