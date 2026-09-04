package com.ermao.library.shared.modules.audio

import com.ermao.library.shared.modules.audio.application.AudioProgressSaveReason
import com.ermao.library.shared.modules.audio.application.AudioProgressSession
import com.ermao.library.shared.modules.audio.application.AudioProgressWriter
import com.ermao.library.shared.modules.audio.application.LocalAudioPublicationFactory
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.ReaderPositionSyncingStore
import com.ermao.library.shared.modules.reader.ReaderPositionDurableState
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class AudioProgressWriterTest {
    @Test
    fun writerPersistsAudioLocatorAndIndependentPresentation() = runBlocking {
        val store = FakeStore()
        var now = 1_000L
        val writer = AudioProgressWriter(store, "resource-1", "device-1") { now }

        writer.save("asset-1", "chapter-1", 2_000, 10_000, AudioProgressSaveReason.Pause)

        val state = store.saved.single()
        assertEquals("asset-1", writer.toAudioLocation(state.position)?.assetId)
        assertEquals(20.0, state.position.presentation.displayPercent)
        assertEquals(2_000, state.position.presentation.playback?.positionMillis)
        assertNotNull(state.position.locator.canonicalJson)
        now += 1
    }

    @Test
    fun sessionUsesRemoteLocatorOnlyWhenNoLocalPendingCapture() = runBlocking {
        val store = FakeStore()
        val writer = AudioProgressWriter(store, "resource-1", "device-1") { 3_000 }
        val session = AudioProgressSession(writer)
        val publication = LocalAudioPublicationFactory().create(
            namespace = ReaderSyncNamespace("server-1", "user-1", 1),
            bookId = "book-1",
            bookTitle = "Book",
            author = null,
            resourceId = "resource-1",
            resourceTitle = "Volume",
            assetId = "asset-1",
            mimeType = "audio/mp4",
            sizeBytes = 1_000,
            durationMillis = 60_000,
        )
        val remote = ReaderProgressSnapshotV5(
            resourceId = "resource-1",
            clientId = "remote-device",
            revision = 2,
            mutationId = "f4743f84-16dc-4202-ab50-729e4d036d16",
            capturedAtEpochMillis = 2_000,
            receivedAtEpochMillis = 2_000,
            position = writerReport("asset-1", 20_000, 60_000),
        )

        assertEquals(20_000, session.restore(publication, remote)?.positionMillis)
    }

    @Test
    fun selectedRemoteAudioLocationIgnoresTheLocalRestoreCandidate() = runBlocking {
        val store = FakeStore()
        val writer = AudioProgressWriter(store, "resource-1", "device-1") { 3_000 }
        val session = AudioProgressSession(writer)
        val publication = LocalAudioPublicationFactory().create(
            namespace = ReaderSyncNamespace("server-1", "user-1", 1),
            bookId = "book-1",
            bookTitle = "Book",
            author = null,
            resourceId = "resource-1",
            resourceTitle = "Volume",
            assetId = "asset-1",
            mimeType = "audio/mp4",
            sizeBytes = 1_000,
            durationMillis = 60_000,
        )
        writer.save("asset-1", null, 5_000, 60_000, AudioProgressSaveReason.Pause)
        val remote = ReaderProgressSnapshotV5(
            resourceId = "resource-1",
            clientId = "remote-device",
            revision = 2,
            mutationId = "f4743f84-16dc-4202-ab50-729e4d036d16",
            capturedAtEpochMillis = 2_000,
            receivedAtEpochMillis = 2_000,
            position = writerReport("asset-1", 20_000, 60_000),
        )

        assertEquals(20_000, session.remoteLocation(publication, remote).positionMillis)
    }

    private fun writerReport(assetId: String, position: Long, duration: Long) =
        com.ermao.library.shared.modules.reader.ReaderPositionReport(
            com.ermao.library.shared.modules.reader.ReaderOpaqueLocator.parse(
                "{\"href\":\"$assetId\",\"type\":\"audio/mp4\",\"locations\":{" +
                    "\"position\":1,\"time\":${position.toDouble() / 1000}}}",
            ),
            com.ermao.library.shared.modules.reader.ReaderPositionPresentation(
                displayPercent = position * 100.0 / duration,
                totalProgression = position.toDouble() / duration,
                currentHref = assetId,
                chapter = null,
                page = null,
                playback = com.ermao.library.shared.modules.reader.ReaderPlaybackPresentation(position, duration),
            ),
        )

    private class FakeStore : ReaderPositionSyncingStore {
        val saved = mutableListOf<ReaderPositionLocalState>()
        var pending = false

        override suspend fun load(resourceId: String): ReaderPositionLocalState? = saved.lastOrNull()
        override suspend fun save(position: ReaderPositionLocalState) {
            saved += position
            pending = true
        }
        override suspend fun delete(resourceId: String) = Unit
        override suspend fun awaitPendingUpload() = Unit
        override suspend fun retryPendingUpload() = Unit
        override suspend fun syncState(): ReaderPositionDurableState = ReaderPositionDurableState()
    }
}
