package com.ermao.library.shared.modules.audio

import com.ermao.library.shared.modules.audio.application.AudioSleepTimer
import com.ermao.library.shared.modules.audio.domain.AudioAsset
import com.ermao.library.shared.modules.audio.domain.AudioLocalArtifact
import com.ermao.library.shared.modules.audio.domain.AudioLocalArtifactIdentity
import com.ermao.library.shared.modules.audio.domain.AudioLocalFallbackPolicy
import com.ermao.library.shared.modules.audio.domain.AudioPublication
import com.ermao.library.shared.modules.audio.domain.AudioResource
import com.ermao.library.shared.modules.audio.domain.AudioSleepTimerMode
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AudioOfflineAndSleepTimerTest {
    @Test
    fun localFallbackRequiresTheCompleteAuthorizationAndAssetIdentity() {
        val publication = publication()
        val asset = publication.assets.single()
        val exact = artifact(publication.namespace, verifiedSize = asset.sizeBytes)
        assertEquals(exact, AudioLocalFallbackPolicy.exactCompletedArtifact(publication, asset, listOf(exact)))

        val staleAuthorization = artifact(
            publication.namespace.copy(authorizationVersion = publication.namespace.authorizationVersion - 1),
            verifiedSize = asset.sizeBytes,
        )
        assertNull(AudioLocalFallbackPolicy.exactCompletedArtifact(publication, asset, listOf(staleAuthorization)))
        assertNull(AudioLocalFallbackPolicy.exactCompletedArtifact(
            publication,
            asset,
            listOf(artifact(publication.namespace, verifiedSize = asset.sizeBytes - 1)),
        ))
    }

    @Test
    fun timerUsesMonotonicTimeAndClearsAfterItFires() {
        var now = 5_000L
        val timer = AudioSleepTimer { now }
        timer.set(AudioSleepTimerMode.Minutes15, "chapter-1", "asset-1")
        now += 15 * 60_000L - 1
        assertFalse(timer.shouldPause("chapter-1", "asset-1", false))
        now += 1
        assertTrue(timer.shouldPause("chapter-1", "asset-1", false))
        assertEquals(AudioSleepTimerMode.Off, timer.snapshot().mode)
    }

    @Test
    fun endOfChapterFallsBackToCurrentTrackWhenNoChapterExists() {
        val timer = AudioSleepTimer { 0 }
        timer.set(AudioSleepTimerMode.EndOfChapter, null, "asset-1")
        assertFalse(timer.shouldPause(null, "asset-1", false))
        assertTrue(timer.shouldPause(null, "asset-1", true))
    }

    private fun publication(): AudioPublication {
        val namespace = ReaderSyncNamespace("server-1", "user-1", 3)
        return AudioPublication(
            namespace = namespace,
            bookId = "book-1",
            bookTitle = "Book",
            author = null,
            coverApiPath = null,
            resource = AudioResource("resource-1", "Volume", ReaderSourceFormat.Mp3, 0, 60_000, 1, 0),
            availableResources = emptyList(),
            assets = listOf(
                AudioAsset(
                    "asset-1", "resource-1", "Track", "/api/assets/asset-1", "audio/mpeg",
                    100, 60_000, null, 1, 0, "mp3",
                ),
            ),
            chapters = emptyList(),
        )
    }

    private fun artifact(namespace: ReaderSyncNamespace, verifiedSize: Long) = AudioLocalArtifact(
        identity = AudioLocalArtifactIdentity(namespace, "book-1", "resource-1", "asset-1"),
        artifactToken = "download-artifact-1",
        verifiedSizeBytes = verifiedSize,
        completed = true,
    )
}
