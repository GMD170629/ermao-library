package com.ermao.library.shared.modules.downloads.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class DownloadsTest {
    @Test
    fun completedCatalogIsNamespaceScopedGroupedByWorkAndSearchable() {
        val primary = namespace("server-a", "user-a", 3)
        val artifacts = listOf(
            artifact(primary, "work-1", "volume-1", "星海纪事", "林青", "上册", 20),
            artifact(primary, "work-1", "volume-2", "星海纪事", "林青", "终章", 30),
            artifact(primary, "work-2", "volume-3", "Quiet Pages", "Mira", "Volume One", 40),
            artifact(namespace("server-a", "user-b", 3), "work-1", "volume-private", "星海纪事", "林青", "私有", 10),
        )

        val all = completedDownloadsByWork(primary, artifacts)
        assertEquals(listOf("work-2", "work-1"), all.map { it.workId })
        val firstWork = all.first { it.workId == "work-1" }
        assertEquals(2, firstWork.artifacts.size)
        assertEquals(50, firstWork.totalBytes)
        assertEquals(listOf("work-1"), completedDownloadsByWork(primary, artifacts, "林青").map { it.workId })
        assertEquals(listOf("work-1"), completedDownloadsByWork(primary, artifacts, "终章").map { it.workId })
        assertEquals(listOf("work-2"), completedDownloadsByWork(primary, artifacts, "quiet").map { it.workId })
    }

    @Test
    fun completedCatalogUsesWorkMediaVersionVolumeHierarchyAndStableLegacyFallback() {
        val primary = namespace("server", "user", 1)
        val current = descriptor(primary, "work", "volume-2", 20, volumeTitle = "Second").copy(
            mediaVersionId = "media-ebook",
            mediaKind = "EBOOK",
            mediaVersionCompleted = true,
            volumeIndex = 2.0,
            volumeSortOrder = 2,
        )
        val first = descriptor(primary, "work", "volume-1", 10, volumeTitle = "First").copy(
            mediaVersionId = "media-ebook",
            mediaKind = "EBOOK",
            mediaVersionCompleted = true,
            volumeIndex = 1.0,
            volumeSortOrder = 1,
        )
        val comic = descriptor(primary, "work", "volume-comic", 30, volumeTitle = "Comic").copy(
            mediaVersionId = "media-comic",
            mediaKind = "COMIC",
            readerType = DownloadReaderType.Comic,
        )
        val legacy = descriptor(primary, "work", "legacy-volume", 40, volumeTitle = "Legacy")

        val work = completedDownloadsByWork(
            primary,
            listOf(artifact(current, 20), artifact(first, 10), artifact(comic, 30), artifact(legacy, 40)),
        ).single()

        assertEquals(listOf("media-ebook", "legacy-volume:legacy-volume", "media-comic"), work.mediaVersions.map { it.mediaVersionId })
        assertEquals(listOf("volume-1", "volume-2"), work.mediaVersions.first().artifacts.map { it.identity.volumeId })
        assertEquals(work.mediaVersions.flatMap { it.artifacts }, work.artifacts)
        assertEquals(listOf("work"), completedDownloadsByWork(primary, work.artifacts, "Legacy").map { it.workId })
    }

    @Test
    fun namespaceIncludesServerUserAndAuthorizationVersion() {
        val keys = setOf(
            namespace("server-a", "user-a", 1).stableKey,
            namespace("server-a", "user-a", 2).stableKey,
            namespace("server-a", "user-b", 1).stableKey,
            namespace("server-b", "user-a", 1).stableKey,
        )
        assertEquals(4, keys.size)
    }

    @Test
    fun taskStateMachineAcceptsExplicitRecoveryAndRejectsIllegalTransitions() {
        val descriptor = descriptor(namespace("server", "user", 1), "work", "volume", 10)
        val queued = DownloadTask("task", descriptor)
        val downloading = queued.transition(DownloadTaskEvent.Start)
            .transition(DownloadTaskEvent.BytesTransferred(4))
        val paused = downloading.transition(DownloadTaskEvent.Pause)
        val resumed = paused.transition(DownloadTaskEvent.Resume)
        val completedArtifact = artifact(descriptor, 10)
        val completed = resumed.transition(DownloadTaskEvent.BytesTransferred(10))
            .transition(DownloadTaskEvent.Complete(completedArtifact))

        assertEquals(DownloadTaskStatus.Completed, completed.status)
        assertEquals(completedArtifact, completed.artifact)
        assertFailsWith<IllegalArgumentException> { queued.transition(DownloadTaskEvent.Pause) }
        assertFailsWith<IllegalArgumentException> { paused.transition(DownloadTaskEvent.BytesTransferred(5)) }
        assertFailsWith<IllegalArgumentException> { completed.transition(DownloadTaskEvent.Cancel) }
        assertFailsWith<IllegalArgumentException> {
            downloading.transition(DownloadTaskEvent.BytesTransferred(3))
        }
    }

    private fun namespace(server: String, user: String, version: Long) = DownloadNamespace(server, user, version)

    private fun descriptor(
        namespace: DownloadNamespace,
        workId: String,
        volumeId: String,
        bytes: Long,
        title: String = workId,
        author: String? = null,
        volumeTitle: String = volumeId,
    ) = DownloadDescriptor(
        identity = DownloadIdentity(namespace, workId, volumeId),
        workTitle = title,
        workAuthor = author,
        coverApiPath = "/api/works/$workId/cover",
        volumeTitle = volumeTitle,
        format = "EPUB",
        readerType = DownloadReaderType.Reflowable,
        source = DownloadSource("/api/volumes/$volumeId/file", "application/epub+zip", bytes),
    )

    private fun artifact(
        namespace: DownloadNamespace,
        workId: String,
        volumeId: String,
        title: String,
        author: String?,
        volumeTitle: String,
        bytes: Long,
    ) = artifact(descriptor(namespace, workId, volumeId, bytes, title, author, volumeTitle), bytes)

    private fun artifact(descriptor: DownloadDescriptor, bytes: Long) = CompletedDownloadArtifact(
        descriptor = descriptor,
        localReference = "local://${descriptor.identity.volumeId}",
        verifiedBytes = bytes,
        completedAtEpochMillis = 1,
    )
}
