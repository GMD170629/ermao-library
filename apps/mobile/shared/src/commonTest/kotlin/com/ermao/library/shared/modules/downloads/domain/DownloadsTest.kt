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
    fun completedCatalogGroupsByWorkThenVersionAndKeepsVolumeOrder() {
        val primary = namespace("server", "user", 1)
        val implicitFirst = descriptor(primary, "work", "volume-2", 20, volumeTitle = "Second").copy(
            versionId = "version-implicit",
            versionSourceKey = IMPLICIT_DOWNLOAD_VERSION_SOURCE_KEY,
            versionSourceName = null,
            versionCompleted = true,
            volumeIndex = 2.0,
            volumeSortOrder = 2,
        )
        val implicitSecond = descriptor(primary, "work", "volume-1", 10, volumeTitle = "First").copy(
            versionId = "version-implicit",
            versionSourceKey = IMPLICIT_DOWNLOAD_VERSION_SOURCE_KEY,
            versionCompleted = true,
            volumeIndex = 1.0,
            volumeSortOrder = 1,
        )
        val named = descriptor(primary, "work", "volume-named", 30, volumeTitle = "Named").copy(
            versionId = "version-named",
            versionSourceKey = "kindle",
            versionSourceName = "Kindle",
            readerType = DownloadReaderType.Pdf,
        )
        val laterNamed = descriptor(primary, "work", "volume-later", 40, volumeTitle = "Later").copy(
            versionId = "version-later",
            versionSourceKey = "web",
            versionSourceName = "Web",
        )

        val work = completedDownloadsByWork(
            primary,
            listOf(
                artifact(implicitFirst, 20),
                artifact(implicitSecond, 10),
                artifact(named, 30),
                artifact(laterNamed, 40),
            ),
        ).single()

        assertEquals(
            listOf("version-implicit", "version-named", "version-later"),
            work.versions.map { it.versionId },
        )
        assertEquals(listOf("volume-1", "volume-2"), work.versions.first().artifacts.map { it.identity.volumeId })
        assertEquals("__implicit__", work.versions.first().sourceKey)
        assertEquals("Kindle", work.versions[1].sourceName)
        assertEquals(work.versions.flatMap { it.artifacts }, work.artifacts)
    }

    @Test
    fun sameVersionKeepsEpubPdfComicAndAudioTogetherWithoutMediaKindGroups() {
        val primary = namespace("server", "user", 1)
        val versionId = "version-shared"
        val artifacts = listOf(
            DownloadReaderType.Reflowable to "EPUB",
            DownloadReaderType.Pdf to "PDF",
            DownloadReaderType.Comic to "CBZ",
            DownloadReaderType.Audio to "AUDIO",
        ).mapIndexed { index, (readerType, format) ->
            artifact(
                descriptor(
                    primary,
                    "work",
                    "volume-$index",
                    10L + index,
                    volumeTitle = format,
                ).copy(
                    format = format,
                    readerType = readerType,
                    versionId = versionId,
                    versionSourceKey = IMPLICIT_DOWNLOAD_VERSION_SOURCE_KEY,
                    volumeSortOrder = index,
                ),
                10L + index,
            )
        }

        val work = completedDownloadsByWork(primary, artifacts).single()
        assertEquals(listOf(versionId), work.versions.map { it.versionId })
        assertEquals(4, work.versions.single().artifacts.size)
        assertEquals(listOf("EPUB", "PDF", "CBZ", "AUDIO"), work.versions.single().artifacts.map { it.descriptor.format })
    }

    @Test
    fun productionDownloadsCodeDoesNotUseMediaVersionContract() {
        val directory = java.io.File("src/commonMain/kotlin/com/ermao/library/shared/modules/downloads")
        val forbidden = listOf(
            "mediaVersionId",
            "mediaVersionCompleted",
            "DownloadedMediaVersion",
            "effectiveMediaVersionId",
            "DownloadMediaKind",
            "parseDownloadMediaKind",
            "legacyMediaVersionId",
            "legacyMediaKind",
        )
        val hits = directory.walkTopDown().filter { it.isFile && it.extension == "kt" }.flatMap { file ->
            val text = file.readText()
            forbidden.filter { token -> token in text }.map { token -> "${file.name}: $token" }
        }.toList()
        assertEquals(emptyList(), hits)
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
        versionId = "version-$volumeId",
        versionSourceKey = IMPLICIT_DOWNLOAD_VERSION_SOURCE_KEY,
        versionSourceName = null,
        versionCompleted = false,
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
