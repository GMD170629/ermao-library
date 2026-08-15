package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.infrastructure.sha256
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import java.nio.file.Files
import kotlin.test.assertEquals
import kotlinx.coroutines.test.runTest
import org.junit.Test

class AndroidDownloadCatalogTest {
    @Test
    fun newerTaskReplacesOlderTaskForSameVolume() = runTest {
        val root = Files.createTempDirectory("download-catalog-version-test").toFile()
        try {
            val catalog = AndroidDownloadCatalog(root)
            val old = record("old-task", "old.bin", 1)
            val current = record("current-task", "current.bin", 2)

            catalog.upsert(old)
            val replaced = catalog.upsert(current)

            assertEquals(listOf(old), replaced)
            assertEquals(listOf(current), catalog.records(current.namespace))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun legacyHashCatalogAndArtifactsAreRemovedWithoutRehashing() = runTest {
        val root = Files.createTempDirectory("download-catalog-legacy-hash-test").toFile()
        val namespace = AndroidDownloadNamespace("server", "user", 3)
        try {
            val namespaceKey = sha256("server|user|3")
            val directory = root.resolve(namespaceKey).apply { mkdirs() }
            val artifacts = directory.resolve("artifacts").apply { mkdirs() }
            artifacts.resolve("legacy.bin").writeBytes(byteArrayOf(1, 2, 3))
            artifacts.resolve("legacy.bin.sha256").writeText("legacy")
            directory.resolve("catalog.json").writeText(
                """{"schemaVersion":1,"records":[{"taskId":"legacy","namespace":{"serverIdentity":"server","userId":"user","authorizationVersion":3},"workId":"work","workTitle":"Book","author":"Author","coverUrl":"/api/works/work/cover","volumeId":"volume","volumeTitle":"Volume","format":"EPUB","readerType":"reflowable","mediaVersionId":"media","mediaKind":"EBOOK","mediaVersionCompleted":false,"contentFingerprint":"sha256:legacy","sourceApiPath":"/api/volumes/volume/file","sourceMimeType":"application/epub+zip","expectedBytes":3,"transferredBytes":3,"status":"Completed","localReference":"$namespaceKey/artifacts/legacy.bin","verified":true,"createdAtEpochMillis":1,"updatedAtEpochMillis":2}]}""",
            )

            assertEquals(emptyList(), AndroidDownloadCatalog(root).records(namespace))
            assertEquals(false, directory.exists())
        } finally {
            root.deleteRecursively()
        }
    }

    private fun record(taskId: String, localReference: String, updatedAt: Long) =
        AndroidDownloadRecord(
            taskId = taskId,
            namespace = AndroidDownloadNamespace("server", "user", 3),
            workId = "work",
            workTitle = "Book",
            author = "Author",
            coverUrl = "/api/works/work/cover",
            volumeId = "volume",
            volumeTitle = "Volume",
            format = "EPUB",
            readerType = "reflowable",
            sourceApiPath = "/api/volumes/volume/file",
            sourceMimeType = "application/epub+zip",
            expectedBytes = 4,
            transferredBytes = 4,
            status = AndroidDownloadStatus.Completed,
            localReference = localReference,
            verified = true,
            createdAtEpochMillis = 1,
            updatedAtEpochMillis = updatedAt,
        )
}
