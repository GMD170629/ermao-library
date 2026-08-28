package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.OnlinePublicationReadResult
import com.ermao.library.shared.modules.reader.application.PublicationResourcePort
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

class OnlinePublicationSessionTest {
    @Test
    fun resourceFailuresExposeStableNativeErrorCodes() {
        assertEquals(ReaderErrorCode.OnlineLimit,
            OnlinePublicationReadResult.Failure("BINARY_TOO_LARGE").errorCode)
        assertEquals(ReaderErrorCode.PublicationChanged,
            OnlinePublicationReadResult.Failure("PUBLICATION_RESOURCE_CHANGED").errorCode)
        val unknownTransport = OnlinePublicationReadResult.Failure("TRANSPORT_FAILURE", OnlinePublicationStage.Chapter)
        assertEquals(ReaderErrorCode.ReaderEngineError, unknownTransport.errorCode)
        assertEquals(mapOf("code" to "TRANSPORT_FAILURE", "stage" to "chapter", "source" to "server"), unknownTransport.readerError.safeContext)
    }

    @Test
    fun decoderRejectionsKeepTheirOriginalCauseAndOnlyExposeTheMetadataStage() {
        for ((stage, code) in listOf(
            OnlinePublicationStage.Manifest to "PUBLICATION_MANIFEST_INVALID",
            OnlinePublicationStage.Positions to "PUBLICATION_POSITIONS_INVALID",
        )) {
            val cause = IllegalArgumentException("private-parser-details")
            val failure = OnlinePublicationFailure.invalidMetadata(stage, cause)
            assertSame(cause, failure.cause)
            assertEquals(code, failure.message)
            assertEquals(ReaderErrorCode.InvalidResponse, failure.errorCode)
            assertEquals(mapOf("code" to code, "stage" to stage.wireValue, "source" to failure.source), failure.readerError.safeContext)
            val nativeFailure = OnlinePublicationFailure.invalidMetadata(stage)
            assertSame(cause, failure.readerError.cause)
            assertEquals(failure.readerError.copy(cause = null), nativeFailure.readerError)
            assertEquals(null, nativeFailure.cause)
        }
        assertFailsWith<IllegalArgumentException> {
            OnlinePublicationFailure.invalidMetadata(OnlinePublicationStage.Chapter)
        }
    }

    @Test
    fun metadataDoesNotReadChaptersAndConcurrentReadsAreCoalesced(): Unit = runBlocking {
        val port = FakeResources()
        val session = OnlinePublicationSession(source(), port)
        try {
            session.open()
            assertEquals(listOf("manifest.json", "positions.json"), port.requests)
            (0..4).map { async { session.read("chapter-0.xhtml") } }.awaitAll()
            assertEquals(1, port.requests.count { it == "chapter-0.xhtml" })
            assertTrue(port.requests.none { it == "chapter-1.xhtml" })
            assertEquals(8 * 1024 * 1024, port.limits.last())
        } finally { session.close() }
    }

    @Test
    fun jumpingDropsDistantBodiesAndClosePreventsFurtherRequests(): Unit = runBlocking {
        val port = FakeResources()
        val session = OnlinePublicationSession(source(), port)
        session.open()
        session.read("chapter-0.xhtml")
        session.read("chapter-4.xhtml")
        session.read("chapter-0.xhtml")
        assertEquals(2, port.requests.count { it == "chapter-0.xhtml" })
        val before = port.requests.size
        assertIs<OnlinePublicationReadResult.Failure>(session.read("../../assets/original"))
        session.close()
        assertIs<OnlinePublicationReadResult.Failure>(session.read("chapter-0.xhtml"))
        assertEquals(before, port.requests.size)
        assertTrue(port.closed)
    }

    @Test
    fun percentEncodedUnicodeNamesRemainReadable(): Unit = runBlocking {
        val chapter = "Text/%E7%AC%AC%E4%B8%80%E7%AB%A0.xhtml"
        val port = FakeResources(listOf(chapter))
        val session = OnlinePublicationSession(source(), port)
        try {
            assertEquals(chapter, session.open().readingOrder.single().href)
            assertIs<OnlinePublicationReadResult.Content>(session.read(chapter))
        } finally { session.close() }
    }

    @Test
    fun encodedTraversalDelimitersInvalidUtf8AndControlCharactersAreRejected(): Unit = runBlocking {
        for (chapter in listOf("%2e%2e/file.xhtml", "Text%2ffile.xhtml", "Text/%252e.xhtml", "Text/%C0%AF.xhtml", "Text/%00.xhtml")) {
            val session = OnlinePublicationSession(source(), FakeResources(listOf(chapter)))
            try {
                val failure = assertFailsWith<OnlinePublicationFailure> { session.open() }
                assertEquals("PUBLICATION_MANIFEST_INVALID", failure.code)
                assertEquals(OnlinePublicationStage.Manifest, failure.stage)
                assertEquals(ReaderErrorCode.InvalidResponse, failure.errorCode)
                assertNotNull(failure.cause)
            }
            finally { session.close() }
        }
    }

    @Test
    fun metadataFailuresKeepTheirServerCauseAndFailedStage(): Unit = runBlocking {
        for ((path, stage) in listOf("manifest.json" to OnlinePublicationStage.Manifest,
            "positions.json" to OnlinePublicationStage.Positions)) {
            val code = "PUBLICATION_TXT_NUL_CHARACTER"
            val port = FakeResources(failures = mapOf(path to code))
            val session = OnlinePublicationSession(source(), port)
            try {
                val failure = assertFailsWith<OnlinePublicationFailure> { session.open() }
                assertEquals(code, failure.code)
                assertEquals(stage, failure.stage)
                assertEquals(ReaderErrorCode.TxtNulCharacter, failure.errorCode)
                assertEquals(mapOf("code" to code, "stage" to stage.wireValue, "source" to failure.source), failure.readerError.safeContext)
                assertTrue(port.requests.none { it.endsWith(".xhtml") })
            } finally { session.close() }
        }
    }

    @Test
    fun invalidMetadataReportsTheResponseStageWithoutExposingParserDetails(): Unit = runBlocking {
        val cases = listOf(
            Triple("manifest.json", byteArrayOf(0xc3.toByte()), OnlinePublicationStage.Manifest),
            Triple("manifest.json", "{private-parser-details".encodeToByteArray(), OnlinePublicationStage.Manifest),
            Triple("manifest.json", """{"readingOrder":[]}""".encodeToByteArray(), OnlinePublicationStage.Manifest),
            Triple("positions.json", byteArrayOf(0xc3.toByte()), OnlinePublicationStage.Positions),
            Triple("positions.json", """{"positions":[]}""".encodeToByteArray(), OnlinePublicationStage.Positions),
        )
        for ((path, bytes, stage) in cases) {
            val session = OnlinePublicationSession(source(), FakeResources(overrides = mapOf(path to bytes)))
            try {
                val failure = assertFailsWith<OnlinePublicationFailure> { session.open() }
                assertEquals(stage, failure.stage)
                assertEquals(ReaderErrorCode.InvalidResponse, failure.errorCode)
                assertNotNull(failure.cause)
                assertEquals(failure.code, failure.message)
                assertTrue(failure.readerError.safeContext.values.none { "private-parser-details" in it })
            } finally { session.close() }
        }
    }

    @Test
    fun failedChaptersAndAncillaryResourcesKeepTheirStagesAndRemainRetryable(): Unit = runBlocking {
        val failures = mutableMapOf("chapter-0.xhtml" to "REQUEST_TIMEOUT", "cover.png" to "FORBIDDEN")
        val port = FakeResources(failures = failures, resourceHrefs = listOf("cover.png"))
        val session = OnlinePublicationSession(source(), port)
        try {
            session.open()
            val chapter = assertIs<OnlinePublicationReadResult.Failure>(session.read("chapter-0.xhtml"))
            assertEquals(OnlinePublicationStage.Chapter, chapter.stage)
            assertEquals(ReaderErrorCode.RequestTimeout, chapter.errorCode)
            val resource = assertIs<OnlinePublicationReadResult.Failure>(session.read("cover.png"))
            assertEquals(OnlinePublicationStage.Resource, resource.stage)
            assertEquals(ReaderErrorCode.Forbidden, resource.errorCode)
            failures.clear()
            assertIs<OnlinePublicationReadResult.Content>(session.read("chapter-0.xhtml"))
            assertIs<OnlinePublicationReadResult.Content>(session.read("cover.png"))
            assertEquals(2, port.requests.count { it == "chapter-0.xhtml" })
            assertEquals(2, port.requests.count { it == "cover.png" })
            assertTrue(port.requests.none { "original" in it || "assets" in it })
        } finally { session.close() }
    }

    @Test
    fun originalTransportExceptionSurvivesMetadataAndChapterFailures(): Unit = runBlocking {
        for (failedPath in listOf("manifest.json", "chapter-0.xhtml")) {
            val cause = IllegalStateException("private-transport-diagnostic")
            val resources = FakeResources()
            val port = object : PublicationResourcePort {
                override suspend fun read(apiPath: String, maximumBytes: Int, mediaTypes: Set<String>): OnlinePublicationReadResult =
                    if (apiPath.endsWith(failedPath)) OnlinePublicationReadResult.Failure(
                        "TLS_FAILURE", cause = cause, source = "transport",
                    ) else resources.read(apiPath, maximumBytes, mediaTypes)
                override fun close() = resources.close()
            }
            val session = OnlinePublicationSession(source(), port)
            try {
                val error = if (failedPath == "manifest.json") {
                    assertFailsWith<OnlinePublicationFailure> { session.open() }.readerError
                } else {
                    session.open()
                    assertIs<OnlinePublicationReadResult.Failure>(session.read(failedPath)).readerError
                }
                assertSame(cause, error.cause)
                assertEquals(ReaderErrorCode.TlsFailure, error.code)
                assertEquals("transport", error.safeContext["source"])
                assertTrue(error.safeContext.values.none { "private" in it })
                assertTrue(resources.requests.none { "assets" in it || "original" in it })
            } finally { session.close() }
        }
    }

    private fun source() = RemoteReflowableReaderSource(
        "resource", "Book", "book", "asset", ReaderSourceFormat.Txt,
        ReaderSyncNamespace("server", "user", 1),
        "/api/reader/v4/resources/resource/publication/manifest.json",
        "/api/reader/v4/resources/resource/publication/positions.json",
    )

    private class FakeResources(
        private val chapters: List<String> = (0..5).map { "chapter-$it.xhtml" },
        private val failures: Map<String, String> = emptyMap(),
        private val overrides: Map<String, ByteArray> = emptyMap(),
        private val resourceHrefs: List<String> = emptyList(),
    ) : PublicationResourcePort {
        val requests = mutableListOf<String>()
        val limits = mutableListOf<Int>()
        var closed = false
        override suspend fun read(apiPath: String, maximumBytes: Int, mediaTypes: Set<String>): OnlinePublicationReadResult {
            val name = apiPath.substringAfterLast('/')
            requests += name
            limits += maximumBytes
            delay(1)
            failures[name]?.let { return OnlinePublicationReadResult.Failure(it) }
            overrides[name]?.let { return OnlinePublicationReadResult.Content(it) }
            val links = chapters.joinToString(",") { """{"href":"$it","type":"application/xhtml+xml"}""" }
            val resources = resourceHrefs.joinToString(",") { """{"href":"$it","type":"image/png"}""" }
            val body = when (name) {
                "manifest.json" -> """{"readingOrder":[$links],"resources":[$resources]}"""
                "positions.json" -> """{"positions":[$links]}"""
                else -> "<html><body>One chapter</body></html>"
            }
            return OnlinePublicationReadResult.Content(body.encodeToByteArray())
        }
        override fun close() { closed = true }
    }
}
