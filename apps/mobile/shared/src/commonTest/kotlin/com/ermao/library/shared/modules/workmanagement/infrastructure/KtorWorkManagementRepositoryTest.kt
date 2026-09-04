package com.ermao.library.shared.modules.workmanagement.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.workmanagement.application.BookManagementSession
import com.ermao.library.shared.modules.workmanagement.application.ManagementPhase
import com.ermao.library.shared.modules.workmanagement.domain.ManagementTarget
import com.ermao.library.shared.modules.workmanagement.domain.ManagementObject
import com.ermao.library.shared.modules.workmanagement.domain.ManagementAction
import com.ermao.library.shared.modules.workmanagement.domain.ManagementField
import com.ermao.library.shared.modules.workmanagement.domain.ManagementFieldValue
import com.ermao.library.shared.modules.workmanagement.domain.ManagementSnapshot
import com.ermao.library.shared.modules.workmanagement.domain.RecognizedField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataApplyOutcome
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.BookMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.ResourceMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.http.content.OutgoingContent
import io.ktor.utils.io.ByteChannel
import io.ktor.utils.io.readRemaining
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.io.readByteArray
import kotlinx.serialization.json.Json

class KtorWorkManagementRepositoryTest {
    @Test fun menuStatePreparationReadsOnlyTheBookEndpoint() = runBlocking {
        val harness = Harness("""{"ok":true,"data":{"book":{"id":"book-1","completed":true}}}""")
        val result = assertIs<WorkManagementResult.Content<Boolean>>(harness.repository.loadBookCompleted(context, "book-1"))
        assertTrue(result.value)
        assertEquals(listOf("/base/api/books/book-1"), harness.requests.map { it.path })
    }

    @Test
    fun bookLevelCommandsUseCurrentBackendContractsWithoutGlobalGate() = runBlocking {
        val harness = Harness(OK, OK, DELETE_RESPONSE, OK)

        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.regenerateBookImage(context, "book-1"),
        )
        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.rescanBook(context, "source-1"),
        )
        assertIs<WorkManagementResult.Content<*>>(
            harness.repository.deleteBook(context, "book-1"),
        )
        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.setBookReadingStatus(context, "book-1", ManagedReadingStatus.Finished),
        )

        assertEquals(
            listOf(
                "/base/api/library/operations/books/covers",
                "/base/api/source-nodes/source-1/continue",
                "/base/api/library/operations/books/delete-sources",
                "/base/api/library/operations/books/reading-status",
            ),
            harness.requests.map(Request::path),
        )
        assertEquals("{\"ids\":[\"book-1\"],\"confirmation\":\"DELETE_SOURCE_FILES\"}", harness.requests[2].body)
        assertEquals("{\"ids\":[\"book-1\"],\"status\":\"FINISHED\"}", harness.requests[3].body)
    }

    @Test
    fun bookEditUsesCurrentBookPatchContract() = runBlocking {
        val harness = Harness(OK)

        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.saveBookFields(
                context,
                "book-1",
                BookMetadataDraft("Updated", "Author", "Description", "Series", 2.0),
            ),
        )

        val request = harness.requests[0]
        assertEquals("PATCH", request.method)
        assertEquals("/base/api/books/book-1", request.path)
        assertTrue(request.body.contains("\"title\":\"Updated\""))
        assertTrue(request.body.contains("\"seriesName\":\"Series\""))
        assertFalse(request.body.contains("tags"))
        assertFalse(request.body.contains("organized"))
    }

    @Test
    fun resourceEditUsesCurrentBookResourcePatchContract() = runBlocking {
        val harness = Harness(RESOURCE_RESPONSE)

        val result = assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.saveResourceFields(
                context,
                "book-1",
                "resource-1",
                listOf(ManagementFieldValue(ManagementField.Publisher, "Publisher"), ManagementFieldValue(ManagementField.Language, "zh-CN"), ManagementFieldValue(ManagementField.Isbn, "123")),
            ),
        )

        val request = harness.requests[0]
        assertEquals("PATCH", request.method)
        assertEquals("/base/api/books/book-1/resources/resource-1", request.path)
        assertTrue(request.body.contains("\"publisher\":\"Publisher\""))
        assertTrue(request.body.contains("\"language\":\"zh-CN\""))
        assertEquals(Unit, result.value)
    }

    @Test
    fun metadataSearchUsesBookSourceNodeRoute() = runBlocking {
        val harness = Harness(METADATA_SEARCH_RESPONSE)

        val result = assertIs<WorkManagementResult.Content<*>>(
            harness.repository.searchMetadata(context, "book-1", "source-1", "openlibrary", "Book"),
        ).value

        val request = harness.requests[0]
        assertEquals("POST", request.method)
        assertEquals("/base/api/books/book-1/source-nodes/source-1/metadata/search", request.path)
        assertTrue(request.body.contains("\"providerId\":\"openlibrary\""))
        assertEquals("Candidate", (result as com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult).candidates.single().title)
    }

    @Test
    fun directoryRecognitionAndResourceCoverUploadUseCurrentContracts() = runBlocking {
        val harness = Harness(OK, RESOURCE_COVER_RESPONSE)
        val candidate = com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate(
            id = "candidate",
            source = "openlibrary",
            title = "Candidate",
            author = null,
            description = null,
            tags = emptyList(),
            seriesName = null,
            publisher = null,
            publishedAt = null,
            language = null,
            isbn = null,
            coverUrl = null,
            confidence = 1.0,
        )

        val apply = harness.repository.applyDirectoryMetadata(context, "book-1", "source-1", candidate.title.orEmpty(), "")
        val upload = harness.repository.uploadCover(
            context,
            "book-1",
            "resource-1",
            CoverUpload("用户封面.jpg", "image/jpeg", "cover-content".encodeToByteArray()),
        )

        assertIs<WorkManagementResult.Content<Unit>>(apply)
        val coverOutcome = assertIs<com.ermao.library.shared.modules.workmanagement.domain.CoverMutationOutcome>(
            assertIs<WorkManagementResult.Content<*>>(upload).value,
        )
        assertEquals("resource-1", coverOutcome.resourceId)
        assertEquals("/api/resources/resource-1/cover", coverOutcome.coverUrl)
        assertEquals("PATCH", harness.requests[0].method)
        assertEquals("/base/api/books/book-1/source-nodes/source-1", harness.requests[0].path)
        assertTrue(harness.requests[0].body.contains("\"title\":\"Candidate\""))
        assertEquals("PUT", harness.requests[1].method)
        assertEquals("/base/api/books/book-1/resources/resource-1/cover", harness.requests[1].path)
        assertTrue(harness.requests[1].contentType?.contains("multipart/form-data") == true)
        assertTrue(harness.requests[1].body.contains("name=\"cover\""))
        assertTrue(harness.requests[1].body.contains("filename=\"cover.jpg\""))
        assertTrue(harness.requests[1].body.contains("cover-content"))
    }

    @Test
    fun coverUploadRejectsMismatchedResourceIdentity() = runBlocking {
        val harness = Harness(MISMATCHED_RESOURCE_COVER_RESPONSE)

        val result = assertIs<WorkManagementResult.Failure>(
            harness.repository.uploadCover(
                context,
                "book-1",
                "resource-1",
                CoverUpload("cover.png", "image/png", byteArrayOf(1)),
            ),
        )

        assertEquals(WorkManagementErrorKind.Protocol, result.error.kind)
        assertEquals("COVER_RESOURCE_IDENTITY_MISMATCH", result.error.code)
    }

    @Test
    fun kindleSendUsesBookAndAssetIdsWithoutBookManagementCapability() = runBlocking {
        val harness = Harness(KINDLE_RESPONSE)

        val result = assertIs<WorkManagementResult.Content<KindleSendOutcome>>(
            harness.repository.sendToKindle(context, "book-1", "asset-1"),
        )

        val request = harness.requests.single()
        assertEquals("POST", request.method)
        assertEquals("/base/api/kindle-send-tasks", request.path)
        assertEquals("{\"bookId\":\"book-1\",\"assetId\":\"asset-1\"}", request.body)
        assertTrue(result.value.alreadyQueued)
    }

    @Test
    fun readingStatusUsesResourceRouteWithoutLegacyVolumePath() = runBlocking {
        val harness = Harness(OK)

        assertIs<WorkManagementResult.Content<Unit>>(
            harness.repository.setReadingStatus(context, "resource-1", ManagedReadingStatus.Finished),
        )

        val request = harness.requests.single()
        assertEquals("PUT", request.method)
        assertEquals("/base/api/reader/v5/resources/resource-1/reading-status", request.path)
        assertEquals("{\"status\":\"FINISHED\"}", request.body)
        assertTrue(harness.requests.none { "/volumes" in it.path })
    }

    @Test
    fun bookCoverRegenerationUsesMultipartWithoutAFileOrRepresentativeResource() = runBlocking {
        val harness = Harness(OK)
        assertIs<WorkManagementResult.Content<Unit>>(harness.repository.regenerateBookImage(context, "book-1"))
        val request = harness.requests.single()
        assertEquals("POST", request.method)
        assertEquals("/base/api/library/operations/books/covers", request.path)
        assertTrue(request.contentType.orEmpty().startsWith("multipart/form-data"))
        listOf("ids", "action", "ratio", "quality", "maxDimension").forEach { assertTrue(request.body.contains("name=\"$it\"")) }
        assertTrue(request.body.contains("[\"book-1\"]"))
        assertTrue(request.body.contains("regenerate"))
        assertFalse(request.body.contains("filename="))
    }

    @Test
    fun sourceCoverCanBeReplacedOrRemovedAndBlankDescriptionIsPreserved() = runBlocking {
        val harness = Harness(OK, OK)
        harness.repository.saveSourcePresentation(context, "book-1", "directory-2", "目录", "", false,
            CoverUpload("用户.png", "image/png", byteArrayOf(1, 2, 3)))
        harness.repository.saveSourcePresentation(context, "book-1", "directory-2", "目录", "", true, null)
        assertTrue(harness.requests.all { it.method == "PUT" && it.path == "/base/api/books/book-1/source-nodes/directory-2" })
        assertTrue(harness.requests.first().body.contains("filename=\"cover.png\""))
        assertTrue(harness.requests.last().body.contains("name=\"description\""))
        assertTrue(harness.requests.last().body.contains("true"))
        assertFalse(harness.requests.last().body.contains("filename="))
    }

    @Test
    fun editorsDistinguishClearedFieldsFromOmittedFields() = runBlocking {
        val harness = Harness(OK, OK)
        harness.repository.saveBookFields(context, "book-1", BookMetadataDraft("Title", "", "", null, null))
        harness.repository.saveResourceFields(context, "book-1", "resource-2", listOf(
            ManagementFieldValue(ManagementField.Publisher, ""), ManagementFieldValue(ManagementField.ResourceIndex, "2.5")))
        assertTrue(harness.requests.first().body.contains("\"seriesName\":null"))
        assertTrue(harness.requests.first().body.contains("\"author\":\"\""))
        assertEquals("{\"publisher\":null,\"resourceIndex\":2.5}", harness.requests.last().body)
    }

    @Test
    fun resourceDeleteCarriesTypedConfirmationAndStableIdempotencyKey() = runBlocking {
        val harness = Harness(OK)
        assertIs<WorkManagementResult.Content<Unit>>(harness.repository.deleteResourceSource(context, "book-1", "resource-2", "卷二", "delete-123"))
        val request = harness.requests.single()
        assertEquals("DELETE", request.method)
        assertEquals("/base/api/books/book-1/resources/resource-2/source", request.path)
        assertEquals("delete-123", request.idempotencyKey)
        assertEquals("{\"confirmation\":\"卷二\"}", request.body)
    }

    @Test
    fun recognitionUsesFullApplyContractAndRetainsPartialResult() = runBlocking {
        val harness = Harness("""{"ok":true,"data":{"appliedFields":["book.author"],"skippedFields":["resource.cover"],"coverStatus":"failed"}}""")
        val candidate = MetadataCandidate("candidate", "provider", "Title", "Author", null, listOf("tag"), null,
            null, null, null, null, "https://covers.example/cover.jpg", 0.9, identifier = "abc", narrator = "Narrator", abridged = false)
        val outcome = assertIs<WorkManagementResult.Content<MetadataApplyOutcome>>(harness.repository.applyRecognizedFields(context,
            ManagementTarget(ManagementObject.Resource, "book-1", "resource-2", "卷二"), candidate,
            listOf(RecognizedField(ManagementObject.Book, ManagementField.Author), RecognizedField(ManagementObject.Resource, ManagementField.Cover)))).value
        val request = harness.requests.single()
        assertEquals("/base/api/books/book-1/metadata/apply", request.path)
        assertEquals("POST", request.method)
        assertTrue(request.body.contains("\"resourceId\":\"resource-2\""))
        assertTrue(request.body.contains("\"abridged\":false"))
        assertEquals(listOf("book.author"), outcome.appliedFields)
        assertEquals(listOf("resource.cover"), outcome.skippedFields)
        assertEquals("failed", outcome.coverStatus)
    }

    @Test
    fun snapshotResolvesExactResourceAcrossPagesAndNeverUsesTheFirstResource() = runBlocking {
        val harness = Harness(BOOK_SNAPSHOT, resourcePage("resource-1", 2), resourcePage("resource-2", 2))
        val snapshot = assertIs<WorkManagementResult.Content<ManagementSnapshot>>(harness.repository.loadManagementSnapshot(context,
            ManagementTarget(ManagementObject.Resource, "book-1", "resource-2", "Target"))).value
        assertEquals(listOf("resource-1", "resource-2"), snapshot.resources.map { it.id })
        assertEquals(listOf(null, "1", "2"), harness.requests.map { it.page })
        val absent = Harness(BOOK_SNAPSHOT, resourcePage("resource-1", 1))
        assertIs<WorkManagementResult.Failure>(absent.repository.loadManagementSnapshot(context,
            ManagementTarget(ManagementObject.Resource, "book-1", "absent", "Absent")))
        Unit
    }

    private fun resourcePage(id: String, pages: Int) = """{"ok":true,"data":{"resources":[{"id":"$id","bookId":"book-1","sourceNodeId":"node-$id","title":"$id","format":"EPUB","kindleSendAvailable":true,"assets":[{"id":"asset-$id","role":"PRIMARY"}]}],"totalPages":$pages}}"""

    private val profile = run {
        val parsed = assertIs<ServerBaseUrlParseResult.Valid>(ServerBaseUrl.parse("https://library.example/base"))
        ServerProfile("profile", "Library", parsed.baseUrl, "server", true, TlsMode.SystemTrust)
    }
    private val context = BookManagementContext(profile, PrivateDataNamespace("server", "user", 1))

    private fun Harness(vararg responses: String) = HarnessFactory(responses.toList())

    private inner class HarnessFactory(responses: List<String>) {
        val requests = mutableListOf<Request>()
        private val pending = ArrayDeque(responses)
        val repository = KtorWorkManagementRepository {
            ApiClient(
                profile,
                HttpClient(MockEngine { request ->
                    val body = request.body.readText()
                    requests += Request(
                        request.method.value,
                        request.url.encodedPath,
                        body,
                        request.body.contentType?.toString() ?: request.headers[HttpHeaders.ContentType],
                        request.headers["Idempotency-Key"],
                        request.url.parameters["page"],
                    )
                    respond(
                        pending.removeFirstOrNull() ?: OK,
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType, "application/json"),
                    )
                }),
                Json { ignoreUnknownKeys = false; explicitNulls = false },
            )
        }
    }

    private suspend fun OutgoingContent.readText(): String = when (this) {
        is OutgoingContent.ByteArrayContent -> bytes().decodeToString()
        is OutgoingContent.ReadChannelContent -> readFrom().readRemaining().readByteArray().decodeToString()
        is OutgoingContent.WriteChannelContent -> coroutineScope {
            val channel = ByteChannel()
            launch {
                try {
                    writeTo(channel)
                } finally {
                    channel.close()
                }
            }
            channel.readRemaining().readByteArray().decodeToString()
        }
        else -> ""
    }

    private data class Request(
        val method: String,
        val path: String,
        val body: String,
        val contentType: String?,
        val idempotencyKey: String?,
        val page: String?,
    )

    private companion object {
        const val BOOK_SNAPSHOT = """{"ok":true,"data":{"book":{"id":"book-1","sourceNodeId":"root-node","title":"Book","author":"Author","tags":[],"completed":false}}}"""
        const val OK = """{"ok":true,"data":{}}"""
        const val RESOURCE_RESPONSE = """{"ok":true,"data":{"resource":{"id":"resource-1","bookId":"book-1"}}}"""
        const val RESOURCE_COVER_RESPONSE = """{"ok":true,"data":{"resource":{"id":"resource-1","bookId":"book-1","coverUrl":"/api/resources/resource-1/cover"}}}"""
        const val MISMATCHED_RESOURCE_COVER_RESPONSE = """{"ok":true,"data":{"resource":{"id":"resource-2","bookId":"book-1","coverUrl":"/api/resources/resource-2/cover"}}}"""
        const val METADATA_SEARCH_RESPONSE = """{"ok":true,"data":{"sourceNodeId":"source-1","providerId":"openlibrary","query":"Book","message":null,"candidates":[{"id":"candidate","source":"openlibrary","title":"Candidate","description":null,"coverUrl":null,"confidence":0.9}]}}"""
        const val KINDLE_RESPONSE = """{"ok":true,"data":{"alreadyQueued":true}}"""
        const val DELETE_RESPONSE = """{"ok":true,"data":{"deletedBookIds":["book-1"]}}"""
    }
}
