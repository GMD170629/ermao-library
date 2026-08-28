package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.DownloadBootstrap
import com.ermao.library.shared.modules.downloads.DownloadBootstrapGateway
import com.ermao.library.shared.modules.downloads.DownloadBootstrapResult
import com.ermao.library.shared.modules.downloads.DownloadBootstrapSuccess
import com.ermao.library.shared.modules.downloads.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.DownloadIdentity
import com.ermao.library.shared.modules.downloads.DownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadReaderType
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.DownloadSource
import com.ermao.library.shared.modules.downloads.DownloadTask
import com.ermao.library.shared.modules.downloads.DownloadTaskStatus
import com.ermao.library.shared.modules.downloads.DownloadSinkRequest
import com.ermao.library.shared.modules.downloads.InMemoryDownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.createDownloadRequestContext
import com.ermao.library.shared.modules.downloads.DownloadBundleMember
import com.ermao.library.shared.modules.downloads.DownloadArtifactKind
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import kotlin.test.assertFailsWith

class ReaderLaunchCoordinatorTest {
    private val context = createDownloadRequestContext("profile", "Books", "https://books.example", "server", false, "user", 1)
    private val namespace: DownloadNamespace = context.namespace
    private val limit = ReaderAdmission.maximumPublicationBytes

    private fun descriptor(bytes: Long = 10, format: String = "epub") = DownloadDescriptor(
        identity = DownloadIdentity(namespace, "book", "resource", "asset"), bookTitle = "Book", bookAuthor = null,
        coverApiPath = null, resourceTitle = "Resource", format = format,
        readerType = DownloadReaderType.Reflowable, source = DownloadSource("/api/assets/asset", "application/octet-stream", bytes),
    )

    private class Metadata(private val descriptor: DownloadDescriptor) : DownloadBootstrapGateway {
        var calls = 0
        override suspend fun load(context: DownloadRequestContext, resourceId: String): DownloadBootstrapResult {
            calls++
            return DownloadBootstrapSuccess(DownloadBootstrap(descriptor))
        }
    }

    @Test fun admissionIsInclusiveAndSeparateFromArrayAllocation() {
        assertTrue(ReaderAdmission.accepts(limit - 1))
        assertTrue(ReaderAdmission.accepts(limit))
        assertFalse(ReaderAdmission.accepts(limit + 1))
        assertTrue(ReaderAdmission.accepts(0))
        assertEquals(null, ReaderAdmission.localFailure("txt", 0))
        assertEquals(null, ReaderAdmission.localFailure("epub", limit))
        assertNotNull(ReaderAdmission.localFailure("txt", limit))
        assertEquals(0.5, ReaderAdmission.progress(limit / 2, limit))
        assertEquals(1.0, ReaderAdmission.progress(limit, limit))
        val request = DownloadSinkRequest(namespace, "task", "resource", "asset", limit, limit - 1)
        assertEquals(limit - 1, request.resumeFromBytes)
        val task = DownloadTask("task", descriptor(limit), DownloadTaskStatus.Downloading, transferredBytes = limit - 1)
        assertEquals(limit - 1, task.transferredBytes)
        assertFailsWith<IllegalArgumentException> { ReaderAdmission.progress(limit + 1, limit) }
    }

    @Test fun coldOnlineLaunchDoesNotCreateAnyDownloadTask() = runBlocking {
        for (size in listOf(limit - 1, limit, limit + 1)) {
            val catalog = InMemoryDownloadCatalogRepository()
            val metadata = Metadata(descriptor(size))
            val decision = ReaderLaunchCoordinator(catalog, metadata).prepare(context, "resource")
            if (size <= limit) assertIs<ReaderLaunchOnline>(decision) else assertIs<ReaderLaunchUnavailable>(decision)
            assertEquals(1, metadata.calls)
            assertTrue(catalog.listTasks(namespace).isEmpty())
            assertTrue(catalog.listArtifacts(namespace).isEmpty())
        }
    }

    @Test fun verifiedLocalArtifactOpensWithoutAnyNetworkCall() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val descriptor = descriptor()
        val artifact = CompletedDownloadArtifact(descriptor, "managed/original", 10, 42)
        catalog.saveTask(DownloadTask("task", descriptor, DownloadTaskStatus.Completed, 10, artifact = artifact))
        val metadata = Metadata(descriptor)
        assertEquals(artifact, assertIs<ReaderLaunchLocal>(ReaderLaunchCoordinator(catalog, metadata).prepare(context, "resource")).artifact)
        assertEquals(0, metadata.calls)
    }

    @Test fun coverVariantsDoNotBlockReadingButCannotEscapeTheApi(): Unit = runBlocking {
        val cover = "/api/books/book/cover?size=medium&v=42"
        val publication = descriptor().copy(coverApiPath = cover)
        val launch = ReaderLaunchCoordinator(InMemoryDownloadCatalogRepository(), Metadata(publication))
            .prepare(context, "resource")
        assertEquals(cover, assertIs<ReaderLaunchOnline>(launch).descriptor.coverApiPath)
        for (unsafe in listOf("https://other.example/cover", "/api/../cover?size=small",
            "/api/books/book/cover#fragment", "/api/books/book/cover?size=small\n")) {
            assertFailsWith<IllegalArgumentException> { publication.copy(coverApiPath = unsafe) }
        }
        assertFailsWith<IllegalArgumentException> { publication.source.copy(apiPath = "/api/assets/asset?download=1") }
    }

    @Test fun onlyNamedOnlineLimitationsCanSelectOneDownload() {
        val descriptor = descriptor()
        for (error in listOf(ReaderErrorCode.NetworkUnavailable, ReaderErrorCode.PublicationChanged,
            ReaderErrorCode.CorruptFile, ReaderErrorCode.ParseFailed, ReaderErrorCode.UnsupportedFormat)) {
            val coordinator = ReaderLaunchCoordinator(InMemoryDownloadCatalogRepository(), Metadata(descriptor))
            assertIs<ReaderLaunchUnavailable>(coordinator.fallback(descriptor, error))
            assertIs<ReaderLaunchDownload>(coordinator.fallback(descriptor, ReaderErrorCode.OnlineLimit))
            assertIs<ReaderLaunchUnavailable>(coordinator.fallback(descriptor, ReaderErrorCode.OnlineLimit))
        }
        val coordinator = ReaderLaunchCoordinator(InMemoryDownloadCatalogRepository(), Metadata(descriptor))
        assertIs<ReaderLaunchDownload>(coordinator.fallbackCode(descriptor, "PDF_RANGE_UNSUPPORTED"))
    }

    @Test fun preciseOnlineFailuresNeverCreateADownloadFallback(): Unit = runBlocking {
        for (code in listOf("UNAUTHORIZED", "FORBIDDEN", "PUBLICATION_NOT_FOUND", "PUBLICATION_RESOURCE_NOT_FOUND",
            "PUBLICATION_CORRUPT", "PUBLICATION_UNSUPPORTED", "PUBLICATION_TXT_NUL_CHARACTER",
            "PUBLICATION_TXT_ENCODING_UNSUPPORTED", "PUBLICATION_TXT_EMPTY", "PUBLICATION_RESPONSE_INVALID",
            "BINARY_CONTENT_TYPE_MISSING", "BINARY_LENGTH_INVALID", "REQUEST_TIMEOUT", "TLS_FAILURE",
            "RATE_LIMITED", "NETWORK_UNAVAILABLE", "SERVER_UNAVAILABLE", "UNKNOWN_MISSING", "TRANSPORT_FAILURE")) {
            val catalog = InMemoryDownloadCatalogRepository()
            val publication = descriptor(format = "txt")
            val coordinator = ReaderLaunchCoordinator(catalog, Metadata(publication))
            val result = assertIs<ReaderLaunchUnavailable>(coordinator.fallbackCode(publication, code), code)
            assertEquals(readerErrorCodeForFailure(code, false), result.code, code)
            assertTrue(catalog.listTasks(namespace).isEmpty(), code)
            assertTrue(catalog.listArtifacts(namespace).isEmpty(), code)
        }
    }

    @Test fun knownLocalEngineLimitsDoNotStartPointlessDownloads() {
        val largeText = descriptor(limit, "txt")
        val coordinator = ReaderLaunchCoordinator(InMemoryDownloadCatalogRepository(), Metadata(largeText))
        assertEquals(ReaderErrorCode.OutOfMemoryRisk,
            assertIs<ReaderLaunchUnavailable>(coordinator.fallback(largeText, ReaderErrorCode.OnlineLimit)).code)
    }

    @Test fun observingAnIndependentDownloadCannotOpenADifferentRevision() = runBlocking {
        val expected = descriptor()
        val changed = expected.copy(source = expected.source.copy(sourceModifiedAtMillis = 2))
        val artifact = CompletedDownloadArtifact(changed, "managed/original", 10, 42)
        val catalog = InMemoryDownloadCatalogRepository()
        catalog.saveTask(DownloadTask("task", changed, DownloadTaskStatus.Completed, 10, artifact = artifact))
        val coordinator = ReaderLaunchCoordinator(catalog, Metadata(expected))
        assertEquals(ReaderErrorCode.PublicationChanged, assertIs<ReaderLaunchUnavailable>(coordinator.complete(expected)).code)
        assertEquals(artifact, assertIs<ReaderLaunchLocal>(coordinator.complete(changed)).artifact)
    }

    @Test fun directoryAdmissionUsesAllMemberBytesAndCannotOverflow() {
        fun bundle(first: Long, second: Long) = descriptor().copy(format = "image_dir", readerType = DownloadReaderType.Comic,
            artifactKind = DownloadArtifactKind.OriginalPageSet, members = listOf(
                DownloadBundleMember("a", 0, DownloadSource("/api/assets/a", "image/jpeg", first)),
                DownloadBundleMember("b", 1, DownloadSource("/api/assets/b", "image/jpeg", second)),
            ))
        assertTrue(ReaderAdmission.accepts(bundle(limit / 2, limit / 2).totalBytes))
        assertFalse(ReaderAdmission.accepts(bundle(limit / 2, limit / 2 + 1).totalBytes))
        assertFailsWith<IllegalArgumentException> { bundle(Long.MAX_VALUE, 1).totalBytes }
    }
}
