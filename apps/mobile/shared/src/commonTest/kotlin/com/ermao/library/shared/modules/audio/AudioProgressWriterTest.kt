package com.ermao.library.shared.modules.audio

import com.ermao.library.shared.modules.audio.application.AudioProgressSaveReason
import com.ermao.library.shared.modules.audio.application.AudioProgressSession
import com.ermao.library.shared.modules.audio.application.AudioProgressWriter
import com.ermao.library.shared.modules.audio.application.LocalAudioPublicationFactory
import com.ermao.library.shared.modules.reader.AudioPublicationLocation
import com.ermao.library.shared.modules.reader.AudioReaderLocation
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressDurableState
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.ReaderProgressSyncingStore
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class AudioProgressWriterTest {
    @Test
    fun writerPersistsEveryStateMachineCaptureWithItsExactPercentage() = runBlocking {
        val store = FakeStore()
        var now = 1_000L
        val writer = AudioProgressWriter(store, "resource-1", "device-1") { now }

        writer.save("asset-1", null, 1_000, 10_000, AudioProgressSaveReason.Tick)
        now += 14_999
        writer.save("asset-1", "chapter-1", 2_000, 10_000, AudioProgressSaveReason.Pause)

        assertEquals(2, store.saved.size)
        val location = assertIs<AudioReaderLocation>(store.saved.last().location)
        assertEquals("chapter-1", location.chapterId)
        assertEquals(20.0, store.saved.last().percent)
    }

    @Test
    fun sessionRestoresNewestValidExactLocationAndFallsBackFromInvalidRemote() = runBlocking {
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
        store.saved += ReaderProgress(
            resourceId = "resource-1",
            location = AudioReaderLocation("asset-1", null, 10_000),
            updatedAtEpochMillis = 1_000,
            deviceId = "device-1",
            percent = 16.67,
        )
        val newerRemote = ReaderProgressSnapshotV4(
            resourceId = "resource-1",
            clientId = "remote-device",
            revision = 2,
            locator = AudioPublicationLocation("asset-1", null, 20_000),
            displayPercent = 33.33,
            receivedAtEpochMillis = 2_000,
            capturedAtEpochMillis = 2_000,
        )

        assertEquals(20_000, session.restore(publication, newerRemote)?.positionMillis)

        val invalidRemote = newerRemote.copy(
            revision = 3,
            locator = AudioPublicationLocation("missing-asset", null, 30_000),
            receivedAtEpochMillis = 3_000,
            capturedAtEpochMillis = 3_000,
        )
        assertEquals(10_000, session.restore(publication, invalidRemote)?.positionMillis)
    }

    private class FakeStore : ReaderProgressSyncingStore {
        val saved = mutableListOf<ReaderProgress>()

        override suspend fun load(sourceId: String): ReaderProgress? = saved.lastOrNull()
        override suspend fun save(progress: ReaderProgress) {
            saved += progress
        }
        override suspend fun delete(sourceId: String) = Unit
        override suspend fun awaitPendingUpload() = Unit
        override suspend fun retryPendingUpload() = Unit
        override suspend fun syncState(): ReaderProgressDurableState = ReaderProgressDurableState()
    }
}
