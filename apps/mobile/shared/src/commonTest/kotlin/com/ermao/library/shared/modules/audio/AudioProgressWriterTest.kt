package com.ermao.library.shared.modules.audio

import com.ermao.library.shared.modules.audio.application.AudioProgressSaveReason
import com.ermao.library.shared.modules.audio.application.AudioProgressWriter
import com.ermao.library.shared.modules.reader.AudioReaderLocation
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressDurableState
import com.ermao.library.shared.modules.reader.ReaderProgressSyncingStore
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue

class AudioProgressWriterTest {
    @Test
    fun ticksAreThrottledButLifecycleIntentionsSaveImmediately() = runBlocking {
        val store = FakeStore()
        var now = 1_000L
        val writer = AudioProgressWriter(store, "resource-1", "device-1") { now }

        assertTrue(writer.save("asset-1", null, 1_000, 10_000, AudioProgressSaveReason.Tick))
        now += 14_999
        assertFalse(writer.save("asset-1", null, 2_000, 10_000, AudioProgressSaveReason.Tick))
        assertTrue(writer.save("asset-1", "chapter-1", 2_000, 10_000, AudioProgressSaveReason.Pause))

        assertEquals(2, store.saved.size)
        val location = assertIs<AudioReaderLocation>(store.saved.last().location)
        assertEquals("chapter-1", location.chapterId)
        assertEquals(20.0, store.saved.last().percent)
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
