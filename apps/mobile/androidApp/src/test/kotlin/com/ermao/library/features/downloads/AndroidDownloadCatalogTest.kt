package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.infrastructure.sha256
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import java.nio.file.Files
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest
import org.junit.Test

class AndroidDownloadCatalogTest {
    @Test
    fun catalogV3CompletedSingleFileMigratesLosslesslyToV4() = runTest {
        val root = Files.createTempDirectory("download-catalog-v3-migration-test").toFile()
        val namespace = AndroidDownloadNamespace("server", "user", 3)
        try {
            val directory = root.resolve(sha256("server|user|3")).apply { mkdirs() }
            val artifact = directory.resolve("artifacts/legacy.bin").apply {
                parentFile?.mkdirs()
                writeBytes(byteArrayOf(1, 2, 3, 4))
            }
            directory.resolve("catalog.json").writeText(
                """{"schemaVersion":3,"records":[{"taskId":"legacy-task","namespace":{"serverIdentity":"server","userId":"user","authorizationVersion":3},"bookId":"book","bookTitle":"Book","author":"Author","coverUrl":"/api/books/book/cover","resourceId":"resource","resourceTitle":"Resource","format":"EPUB","readerType":"reflowable","assetId":"asset","sourceApiPath":"/api/assets/asset","sourceMimeType":"application/epub+zip","expectedBytes":4,"transferredBytes":4,"status":"Completed","localReference":"artifacts/legacy.bin","verified":true,"createdAtEpochMillis":1,"updatedAtEpochMillis":2}]}""",
            )

            val records = AndroidDownloadCatalog(root).records(namespace)

            assertEquals(1, records.size)
            assertEquals("asset", records.single().assetId)
            assertEquals("SingleOriginalAsset", records.single().artifactKind)
            assertTrue(artifact.isFile)
            assertTrue(directory.resolve("catalog.json").readText().contains("\"schemaVersion\":4"))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun newSourceVersionPreservesPreviousUserDownload() = runTest {
        val root = Files.createTempDirectory("download-catalog-version-test").toFile()
        try {
            val catalog = AndroidDownloadCatalog(root)
            val old = record("old-task", "old.bin", 1, assetId = "asset-1")
            val current = record("current-task", "current.bin", 2, assetId = "asset-1")

            catalog.upsert(old)
            val replaced = catalog.upsert(current)

            assertEquals(emptyList(), replaced)
            assertEquals(listOf(current, old), catalog.records(current.namespace))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun unsupportedSchemaFailsWithoutDeletingUserFiles() = runTest {
        val root = Files.createTempDirectory("download-catalog-unsupported-schema-test").toFile()
        val namespace = AndroidDownloadNamespace("server", "user", 3)
        try {
            val namespaceKey = sha256("server|user|3")
            val directory = root.resolve(namespaceKey).apply { mkdirs() }
            val artifacts = directory.resolve("artifacts").apply { mkdirs() }
            artifacts.resolve("legacy.bin").writeBytes(byteArrayOf(1, 2, 3))
            artifacts.resolve("legacy.bin.sha256").writeText("legacy")
            directory.resolve("catalog.json").writeText(
                """{"schemaVersion":1,"records":[]}""",
            )

            assertFailsWith<com.ermao.library.features.downloads.infrastructure.AndroidDownloadStorageException> {
                AndroidDownloadCatalog(root).records(namespace)
            }
            assertTrue(artifacts.resolve("legacy.bin").exists())
            assertTrue(directory.resolve("catalog.json").exists())
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun exactAzw3UserDownloadRoundTripsWithoutFormatRewriting() = runTest {
        val root = Files.createTempDirectory("download-catalog-azw3-test").toFile()
        val namespace = AndroidDownloadNamespace("server", "user", 3)
        try {
            val namespaceKey = sha256("server|user|3")
            val localReference = "$namespaceKey/artifacts/book.azw3"
            val artifact = root.resolve(localReference).apply {
                parentFile?.mkdirs()
                writeBytes(byteArrayOf(1, 2, 3, 4))
            }
            val catalog = AndroidDownloadCatalog(root)
            catalog.upsert(record("azw3", localReference, 2, format = "AZW3"))

            assertEquals("AZW3", AndroidDownloadCatalog(root).records(namespace).single().format)
            assertTrue(artifact.exists())
            assertTrue(root.resolve(namespaceKey).resolve("catalog.json").readText().contains("AZW3"))
        } finally {
            root.deleteRecursively()
        }
    }

    private fun record(
        taskId: String,
        localReference: String,
        updatedAt: Long,
        assetId: String = "asset-$taskId",
        format: String = "EPUB",
    ) =
        AndroidDownloadRecord(
            taskId = taskId,
            namespace = AndroidDownloadNamespace("server", "user", 3),
            bookId = "book",
            bookTitle = "Book",
            author = "Author",
            coverUrl = "/api/books/book/cover",
            resourceId = "resource",
            resourceTitle = "Resource",
            format = format,
            readerType = "reflowable",
            assetId = assetId,
            sourceApiPath = "/api/resources/resource/asset",
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
