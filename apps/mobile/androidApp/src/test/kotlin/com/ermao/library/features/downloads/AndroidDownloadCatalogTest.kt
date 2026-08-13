package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import java.nio.file.Files
import kotlin.test.assertEquals
import kotlinx.coroutines.test.runTest
import org.junit.Test

class AndroidDownloadCatalogTest {
    @Test
    fun newerFingerprintReplacesOlderVersionOfSameVolume() = runTest {
        val root = Files.createTempDirectory("download-catalog-version-test").toFile()
        try {
            val catalog = AndroidDownloadCatalog(root)
            val old = record("old-task", "old-fingerprint", "old.bin", 1)
            val current = record("current-task", "current-fingerprint", "current.bin", 2)

            catalog.upsert(old)
            val replaced = catalog.upsert(current)

            assertEquals(listOf(old), replaced)
            assertEquals(listOf(current), catalog.records(current.namespace))
        } finally {
            root.deleteRecursively()
        }
    }

    private fun record(taskId: String, fingerprint: String, localReference: String, updatedAt: Long) =
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
            contentFingerprint = fingerprint,
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
