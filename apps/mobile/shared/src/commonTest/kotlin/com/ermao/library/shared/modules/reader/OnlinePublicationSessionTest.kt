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
import kotlin.test.assertTrue

class OnlinePublicationSessionTest {
    @Test
    fun resourceFailuresExposeStableNativeErrorCodes() {
        assertEquals(ReaderErrorCode.OutOfMemoryRisk,
            OnlinePublicationReadResult.Failure("BINARY_TOO_LARGE").errorCode)
        assertEquals(ReaderErrorCode.PublicationChanged,
            OnlinePublicationReadResult.Failure("PUBLICATION_RESOURCE_CHANGED").errorCode)
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
            try { assertFailsWith<IllegalArgumentException> { session.open() } }
            finally { session.close() }
        }
    }

    private fun source() = RemoteReflowableReaderSource(
        "resource", "Book", "book", "asset", ReaderSourceFormat.Txt,
        ReaderSyncNamespace("server", "user", 1),
        "/api/reader/v4/resources/resource/publication/manifest.json",
        "/api/reader/v4/resources/resource/publication/positions.json",
    )

    private class FakeResources(private val chapters: List<String> = (0..5).map { "chapter-$it.xhtml" }) : PublicationResourcePort {
        val requests = mutableListOf<String>()
        val limits = mutableListOf<Int>()
        var closed = false
        override suspend fun read(apiPath: String, maximumBytes: Int, mediaTypes: Set<String>): OnlinePublicationReadResult {
            val name = apiPath.substringAfterLast('/')
            requests += name
            limits += maximumBytes
            delay(1)
            val links = chapters.joinToString(",") { """{"href":"$it","type":"application/xhtml+xml"}""" }
            val body = when (name) {
                "manifest.json" -> """{"readingOrder":[$links]}"""
                "positions.json" -> """{"positions":[$links]}"""
                else -> "<html><body>One chapter</body></html>"
            }
            return OnlinePublicationReadResult.Content(body.encodeToByteArray())
        }
        override fun close() { closed = true }
    }
}
