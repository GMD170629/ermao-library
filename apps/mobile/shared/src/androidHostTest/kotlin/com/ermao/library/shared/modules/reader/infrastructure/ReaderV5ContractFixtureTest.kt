package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.modules.reader.application.ReaderPositionPushResult
import com.ermao.library.shared.modules.reader.application.ReaderPositionQueryResult
import com.ermao.library.shared.modules.reader.application.ReaderPositionUpload
import com.ermao.library.shared.modules.reader.domain.ReaderFormat
import com.ermao.library.shared.modules.reader.domain.ReaderProgressMutationV5
import com.ermao.library.shared.modules.reader.domain.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.http.content.TextContent
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The contract fixtures live in packages/reader-contracts, so both mobile platforms exercise the
 * same JSON rather than maintaining a second hand-copied fixture set.  This host test is wired to
 * the repository fixture directory by shared/build.gradle.kts.
 */
class ReaderV5ContractFixtureTest {
    private val json = Json { ignoreUnknownKeys = false }
    private val mapper = ReaderV5ServerWireMapper()
    private val reportJson = ReaderPositionReportJson(mapper)

    @Test
    fun allReaderV5FormatFixturesRoundTripTheirPositionWithoutLosingLocatorFields() {
        listOf("reflowable-empty-highlight", "pdf", "comic", "audio").forEach { name ->
            val root = fixture(name)
            assertEquals(5L, root.requiredLong("schemaVersion"))
            assertTrue(root.requiredString("clientId").isNotBlank())
            assertTrue(root.requiredString("mutationId").isNotBlank())

            val originalPosition = root.requiredObject("position")
            val originalLocator = originalPosition.requiredObject("locator")
            val report = mapper.decodePosition(originalPosition)
            val encoded = json.parseToJsonElement(reportJson.encode(report)).jsonObject
            assertJsonEquivalent(originalPosition, encoded)

            val decoded = reportJson.decode(encoded.toString())
            assertJsonEquivalent(
                originalLocator,
                json.parseToJsonElement(decoded.locator.canonicalJson),
            )
            assertJsonEquivalent(
                originalPosition.requiredObject("presentation"),
                mapper.encodePosition(decoded).requiredObject("presentation"),
            )
        }
    }

    @Test
    fun fixturePresentationRemainsIndependentFromOpaqueLocatorProgression() {
        val reflow = fixture("reflowable-empty-highlight").requiredObject("position")
        val locator = reflow.requiredObject("locator")
        val presentation = reflow.requiredObject("presentation")
        assertEquals(0.25, locator.requiredObject("locations").requiredDouble("totalProgression"))
        assertEquals(0.99, presentation.requiredDouble("totalProgression"))

        val audio = fixture("audio").requiredObject("position")
        assertEquals(0.35, audio.requiredObject("locator").requiredObject("locations").requiredDouble("totalProgression"))
        assertEquals(0.35, audio.requiredObject("presentation").requiredDouble("totalProgression"))
    }

    @Test
    fun writeSuccessEnvelopeIsAcceptedThroughProductionApiClient() = runBlocking {
        for (name in listOf("audio", "reflowable-empty-highlight", "pdf", "comic")) {
            val request = fixture(name)
            val snapshot = snapshot(request)
            var requestCount = 0
            val port = port { sent ->
                requestCount += 1
                assertEquals(HttpMethod.Put, sent.method)
                assertEquals("/api/reader/v5/resources/resource-1/progress", sent.url.encodedPath)
                assertJsonEquivalent(request, json.parseToJsonElement(assertIs<TextContent>(sent.body).text))
                respond(
                    successEnvelope(writeResponseData(request, snapshot)),
                    HttpStatusCode.OK,
                    headersOf(HttpHeaders.ContentType, "application/json"),
                )
            }

            val result = port.push(upload(request))

            val accepted = assertIs<ReaderPositionPushResult.Accepted>(result, "$name: $result").response
            assertEquals(1, requestCount)
            assertEquals(request.requiredString("mutationId"), accepted.acceptedMutationId)
            assertEquals(4L, accepted.acceptedRevision)
            assertEquals(4L, accepted.currentSnapshot.revision)
            assertEquals("resource-1", accepted.currentSnapshot.resourceId)
            assertEquals(request.requiredString("clientId"), accepted.currentSnapshot.clientId)
            assertEquals(request.requiredLong("capturedAtEpochMillis"), accepted.currentSnapshot.capturedAtEpochMillis)
            assertJsonEquivalent(request.requiredObject("position"), mapper.encodePosition(accepted.currentSnapshot.position))
        }
    }

    @Test
    fun writeResponseMayAcknowledgeAnOlderMutationThanCurrentSnapshot() = runBlocking {
        val request = fixture("audio")
        val current = JsonObject(snapshot(fixture("pdf")) + ("revision" to JsonPrimitive(9)))
        val port = port {
            respond(
                successEnvelope(writeResponseData(request, current)),
                HttpStatusCode.OK,
                headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }

        val accepted = assertIs<ReaderPositionPushResult.Accepted>(port.push(upload(request))).response

        assertEquals(request.requiredString("mutationId"), accepted.acceptedMutationId)
        assertEquals(4L, accepted.acceptedRevision)
        assertEquals(current.requiredString("mutationId"), accepted.currentSnapshot.mutationId)
        assertEquals(9L, accepted.currentSnapshot.revision)
        assertJsonEquivalent(current.requiredObject("position"), mapper.encodePosition(accepted.currentSnapshot.position))
    }

    @Test
    fun writeResponsesRejectMalformedAcknowledgementsAndSnapshots() = runBlocking {
        val request = fixture("audio")
        val current = snapshot(request)
        val valid = writeResponseData(request, current)
        val position = current.requiredObject("position")
        val invalidSnapshots = listOf(
            "missing snapshot field" to JsonObject(current - "receivedAtEpochMillis"),
            "unknown snapshot field" to JsonObject(current + ("unexpected" to JsonPrimitive(true))),
            "unsupported schema" to JsonObject(current + ("schemaVersion" to JsonPrimitive(4))),
            "nonpositive revision" to JsonObject(current + ("revision" to JsonPrimitive(0))),
            "invalid mutation UUID" to JsonObject(current + ("mutationId" to JsonPrimitive("invalid"))),
            "blank client" to JsonObject(current + ("clientId" to JsonPrimitive(" "))),
            "negative capture time" to JsonObject(current + ("capturedAtEpochMillis" to JsonPrimitive(-1))),
            "invalid Locator" to JsonObject(current + ("position" to JsonObject(
                position + ("locator" to JsonPrimitive("invalid")),
            ))),
            "invalid presentation" to JsonObject(current + ("position" to JsonObject(
                position + ("presentation" to JsonObject(
                    position.requiredObject("presentation") + ("displayPercent" to JsonPrimitive(101)),
                )),
            ))),
        )
        val invalidResponses = listOf(
            "missing acknowledgement" to JsonObject(valid - "acceptedMutationId"),
            "invalid acknowledgement UUID" to JsonObject(valid + ("acceptedMutationId" to JsonPrimitive("invalid"))),
            "missing revision" to JsonObject(valid - "acceptedRevision"),
            "nonpositive accepted revision" to JsonObject(valid + ("acceptedRevision" to JsonPrimitive(0))),
            "string accepted revision" to JsonObject(valid + ("acceptedRevision" to JsonPrimitive("4"))),
            "fractional accepted revision" to JsonObject(valid + ("acceptedRevision" to JsonPrimitive(4.5))),
            "null snapshot" to JsonObject(valid + ("currentSnapshot" to JsonNull)),
            "unknown acknowledgement field" to JsonObject(valid + ("unexpected" to JsonPrimitive(true))),
            "nested envelope" to json.parseToJsonElement(successEnvelope(valid)).jsonObject,
        ) + invalidSnapshots.map { (label, invalid) ->
            label to JsonObject(valid + ("currentSnapshot" to invalid))
        }

        for ((label, response) in invalidResponses) {
            val port = port {
                respond(successEnvelope(response), HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            }

            assertEquals(
                ReaderPositionPushResult.Rejected("INVALID_PROGRESS_RESPONSE"),
                port.push(upload(request)),
                label,
            )
        }
    }

    @Test
    fun writeRequiresSuccessfulEnvelopeBeforeDecodingAcknowledgement() = runBlocking {
        val request = fixture("audio")
        val unwrapped = writeResponseData(request, snapshot(request))
        val invalidEnvelopes = listOf(
            "malformed JSON" to "{",
            "unwrapped acknowledgement" to unwrapped.toString(),
            "missing data" to "{\"ok\":true}",
            "null data" to "{\"ok\":true,\"data\":null}",
            "array data" to "{\"ok\":true,\"data\":[]}",
            "failed envelope without error" to "{\"ok\":false}",
        )
        for ((label, response) in invalidEnvelopes) {
            val port = port {
                respond(response, HttpStatusCode.OK, headersOf(HttpHeaders.ContentType, "application/json"))
            }

            assertEquals(ReaderPositionPushResult.Rejected("PROTOCOL_VIOLATION"), port.push(upload(request)), label)
        }
    }

    @Test
    fun writePreservesHttpFailureClassification() = runBlocking {
        val retryable = listOf(
            HttpStatusCode.Unauthorized to "UNAUTHORIZED",
            HttpStatusCode.TooManyRequests to "RATE_LIMITED",
            HttpStatusCode.InternalServerError to "SERVER_FAILURE",
            HttpStatusCode.ServiceUnavailable to "UNAVAILABLE",
        )
        val rejected = listOf(
            HttpStatusCode.Forbidden to "FORBIDDEN",
            HttpStatusCode.NotFound to "NOT_FOUND",
            HttpStatusCode.Conflict to "READER_PROGRESS_MUTATION_REUSE",
            HttpStatusCode.UnprocessableEntity to "VALIDATION",
        )
        val request = upload(fixture("audio"))
        for ((status, code) in retryable + rejected) {
            val port = port {
                respond(failureEnvelope(code), status, headersOf(HttpHeaders.ContentType, "application/json"))
            }
            val expected = if ((status to code) in retryable) {
                ReaderPositionPushResult.RetryableFailure(code)
            } else {
                ReaderPositionPushResult.Rejected(code)
            }

            assertEquals(expected, port.push(request), status.toString())
        }
    }

    @Test
    fun retrySendsTheSameMutationBody() = runBlocking {
        val request = fixture("audio")
        val bodies = mutableListOf<String>()
        val port = port { sent ->
            bodies += assertIs<TextContent>(sent.body).text
            if (bodies.size == 1) {
                respond(
                    failureEnvelope("UNAVAILABLE"), HttpStatusCode.ServiceUnavailable,
                    headersOf(HttpHeaders.ContentType, "application/json"),
                )
            } else {
                respond(
                    successEnvelope(writeResponseData(request, snapshot(request))), HttpStatusCode.OK,
                    headersOf(HttpHeaders.ContentType, "application/json"),
                )
            }
        }
        val upload = upload(request)

        assertEquals(ReaderPositionPushResult.RetryableFailure("UNAVAILABLE"), port.push(upload))
        val accepted = assertIs<ReaderPositionPushResult.Accepted>(port.push(upload)).response

        assertEquals(2, bodies.size)
        assertEquals(bodies[0], bodies[1])
        assertJsonEquivalent(request, json.parseToJsonElement(bodies[1]))
        assertEquals(request.requiredString("mutationId"), accepted.acceptedMutationId)
    }

    @Test
    fun writePropagatesCancellation() = runBlocking {
        val port = port { throw CancellationException("cancelled progress request") }

        val cancelled = assertFailsWith<CancellationException> { port.push(upload(fixture("audio"))) }

        assertEquals("cancelled progress request", cancelled.message)
    }

    @Test
    fun crossServerTargetsNeverReachHttp() = runBlocking {
        var requests = 0
        val port = port {
            requests += 1
            respond("unexpected request")
        }
        val request = upload(fixture("audio"))
        val otherServer = request.target.copy(namespace = ReaderSyncNamespace("other-server", "user-1", 1))

        assertFailsWith<IllegalArgumentException> { port.push(request.copy(target = otherServer)) }
        assertFailsWith<IllegalArgumentException> { port.load(otherServer, null) }
        assertEquals(0, requests)
    }

    @Test
    fun progressQueryKeepsEnvelopeAndEtagContract() = runBlocking {
        val request = fixture("audio")
        val current = snapshot(request)
        val target = upload(request).target
        for (remote in listOf(current, JsonNull)) {
            val port = port { sent ->
                assertEquals(HttpMethod.Get, sent.method)
                assertEquals("/api/reader/v5/resources/resource-1/progress", sent.url.encodedPath)
                respond(
                    successEnvelope(JsonObject(mapOf("schemaVersion" to JsonPrimitive(5), "progressSnapshot" to remote))),
                    HttpStatusCode.OK,
                    headersOf(HttpHeaders.ContentType to listOf("application/json"), HttpHeaders.ETag to listOf("\"progress-4\"")),
                )
            }

            val loaded = assertIs<ReaderPositionQueryResult.Current>(port.load(target, null))

            assertEquals("\"progress-4\"", loaded.etag)
            if (remote == JsonNull) {
                assertNull(loaded.snapshot)
            } else {
                val restored = requireNotNull(loaded.snapshot)
                assertEquals(4L, restored.revision)
                assertEquals(request.requiredString("mutationId"), restored.mutationId)
                assertJsonEquivalent(request.requiredObject("position"), mapper.encodePosition(restored.position))
            }
        }
        val unchanged = port { sent ->
            assertEquals("\"progress-4\"", sent.headers[HttpHeaders.IfNoneMatch])
            respond("", HttpStatusCode.NotModified, headersOf(HttpHeaders.ETag, "\"progress-4\""))
        }
        assertEquals(ReaderPositionQueryResult.Unchanged("\"progress-4\""), unchanged.load(target, "\"progress-4\""))
        val invalid = port {
            respond(
                successEnvelope(JsonObject(mapOf("schemaVersion" to JsonPrimitive(4), "progressSnapshot" to current))),
                HttpStatusCode.OK,
                headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        assertEquals(ReaderPositionQueryResult.Failure("INVALID_PROGRESS_RESPONSE", false), invalid.load(target, null))
    }

    private fun snapshot(request: JsonObject): JsonObject = JsonObject(
        request + mapOf(
            "revision" to JsonPrimitive(4),
            "receivedAtEpochMillis" to JsonPrimitive(request.requiredLong("capturedAtEpochMillis") + 100),
        ),
    )

    private fun writeResponseData(request: JsonObject, snapshot: JsonObject): JsonObject = JsonObject(
        mapOf(
            "acceptedMutationId" to request.getValue("mutationId"),
            "acceptedRevision" to JsonPrimitive(4),
            "currentSnapshot" to snapshot,
        ),
    )

    private fun successEnvelope(responseData: JsonObject): String = JsonObject(
        mapOf("ok" to JsonPrimitive(true), "data" to responseData),
    ).toString()

    private fun failureEnvelope(code: String): String = JsonObject(
        mapOf("ok" to JsonPrimitive(false), "error" to JsonObject(mapOf("code" to JsonPrimitive(code)))),
    ).toString()

    private fun upload(request: JsonObject): ReaderPositionUpload = ReaderPositionUpload(
        target = ReaderProgressSyncTarget(
            ReaderSyncNamespace("server-1", "user-1", 1), "book-1", "resource-1", ReaderFormat.Audio,
        ),
        mutation = ReaderProgressMutationV5(
            resourceId = "resource-1",
            clientId = request.requiredString("clientId"),
            mutationId = request.requiredString("mutationId"),
            capturedAtEpochMillis = request.requiredLong("capturedAtEpochMillis"),
            position = mapper.decodePosition(request.requiredObject("position")),
        ),
    )

    private fun port(
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ): KtorReaderPositionSyncPort {
        val baseUrl = assertIs<ServerBaseUrlParseResult.Valid>(ServerBaseUrl.parse("https://books.example")).baseUrl
        val profile = ServerProfile("profile-1", "Books", baseUrl, "server-1", true, TlsMode.SystemTrust)
        return KtorReaderPositionSyncPort(
            profile = profile,
            createClient = { ApiClient(it, HttpClient(MockEngine(handler)), json) },
        )
    }

    private fun fixture(name: String): JsonObject {
        val root = File(
            requireNotNull(System.getProperty("readerV5FixtureRoot")) {
                "readerV5FixtureRoot was not configured"
            },
            "$name.json",
        )
        assertTrue(root.isFile, "Reader v5 fixture does not exist: ${root.absolutePath}")
        return json.parseToJsonElement(root.readText()).jsonObject
    }
}

private fun JsonObject.requiredObject(name: String): JsonObject =
    get(name) as? JsonObject ?: error("Missing object: $name")

private fun JsonObject.requiredString(name: String): String =
    (get(name) as? JsonPrimitive)?.content?.takeIf(String::isNotBlank)
        ?: error("Missing string: $name")

private fun JsonObject.requiredLong(name: String): Long =
    (get(name) as? JsonPrimitive)?.longOrNull ?: error("Missing long: $name")

private fun JsonObject.requiredDouble(name: String): Double =
    (get(name) as? JsonPrimitive)?.doubleOrNull ?: error("Missing double: $name")

private fun assertJsonEquivalent(expected: JsonElement, actual: JsonElement) {
    when {
        expected is JsonObject && actual is JsonObject -> {
            assertEquals(expected.keys, actual.keys)
            expected.keys.forEach { key ->
                assertJsonEquivalent(expected.getValue(key), actual.getValue(key))
            }
        }
        expected is JsonArray && actual is JsonArray -> {
            assertEquals(expected.size, actual.size)
            expected.indices.forEach { index -> assertJsonEquivalent(expected[index], actual[index]) }
        }
        expected == JsonNull || actual == JsonNull -> assertEquals(expected, actual)
        expected is JsonPrimitive && actual is JsonPrimitive -> {
            if (expected.isString || actual.isString) {
                assertEquals(expected.content, actual.content)
            } else {
                assertEquals(expected.doubleOrNull, actual.doubleOrNull)
            }
        }
        else -> assertEquals(expected, actual)
    }
}
