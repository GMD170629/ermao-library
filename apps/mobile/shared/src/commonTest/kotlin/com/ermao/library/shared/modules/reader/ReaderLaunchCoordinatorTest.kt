package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.DownloadBootstrap
import com.ermao.library.shared.modules.downloads.DownloadBootstrapFailure
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

    private class FailingMetadata(private val kind: AppErrorKind) : DownloadBootstrapGateway {
        override suspend fun load(context: DownloadRequestContext, resourceId: String): DownloadBootstrapResult =
            DownloadBootstrapFailure(AppError(kind, kind.name.uppercase()))
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

    @Test fun coldReflowableLaunchRequiresOriginalWithoutCreatingATask() = runBlocking {
        for (size in listOf(limit - 1, limit, limit + 1)) {
            val catalog = InMemoryDownloadCatalogRepository()
            val metadata = Metadata(descriptor(size))
            val decision = ReaderLaunchCoordinator(catalog, metadata).prepare(context, "resource")
            if (size <= limit) assertIs<ReaderLaunchDownload>(decision) else assertIs<ReaderLaunchUnavailable>(decision)
            assertEquals(1, metadata.calls)
            assertTrue(catalog.listTasks(namespace).isEmpty())
            assertTrue(catalog.listArtifacts(namespace).isEmpty())
        }
    }

    @Test fun verifiedLocalArtifactOpensOnlyAfterFreshDescriptorValidation() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val descriptor = descriptor()
        val artifact = CompletedDownloadArtifact(descriptor, "managed/original", 10, 42)
        catalog.saveTask(DownloadTask("task", descriptor, DownloadTaskStatus.Completed, 10, artifact = artifact))
        val metadata = Metadata(descriptor)
        assertEquals(artifact, assertIs<ReaderLaunchLocal>(ReaderLaunchCoordinator(catalog, metadata).prepare(context, "resource")).artifact)
        assertEquals(1, metadata.calls)
    }

    @Test fun verifiedReflowableArtifactOpensWhenTheServerProvidesNoAuthoritativeResponse() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val descriptor = descriptor()
        val older = CompletedDownloadArtifact(descriptor, "managed/older", 10, 41)
        val latest = CompletedDownloadArtifact(descriptor, "managed/latest", 10, 42)
        catalog.saveTask(DownloadTask("older", descriptor, DownloadTaskStatus.Completed, 10, artifact = older))
        catalog.saveTask(DownloadTask("latest", descriptor, DownloadTaskStatus.Completed, 10, artifact = latest))

        for (kind in listOf(
            AppErrorKind.NetworkUnavailable,
            AppErrorKind.Timeout,
            AppErrorKind.TlsFailure,
            AppErrorKind.ServiceUnavailable,
            AppErrorKind.ServerFailure,
        )) {
            val launch = ReaderLaunchCoordinator(catalog, FailingMetadata(kind)).prepare(context, "resource")
            assertEquals(latest, assertIs<ReaderLaunchLocal>(launch).artifact)
        }
    }

    @Test fun authoritativeFailuresNeverFallBackToACompletedArtifact() = runBlocking {
        val catalog = InMemoryDownloadCatalogRepository()
        val descriptor = descriptor()
        val artifact = CompletedDownloadArtifact(descriptor, "managed/original", 10, 42)
        catalog.saveTask(DownloadTask("task", descriptor, DownloadTaskStatus.Completed, 10, artifact = artifact))

        for (kind in listOf(
            AppErrorKind.Unauthorized,
            AppErrorKind.Forbidden,
            AppErrorKind.NotFoundOrUnavailable,
            AppErrorKind.Gone,
            AppErrorKind.Conflict,
            AppErrorKind.ProtocolViolation,
        )) {
            assertIs<ReaderLaunchUnavailable>(
                ReaderLaunchCoordinator(catalog, FailingMetadata(kind)).prepare(context, "resource"),
            )
        }
    }

    @Test fun offlineFallbackIsResourceScopedAndReflowableOnly() = runBlocking {
        suspend fun decision(stored: DownloadDescriptor, requestedResourceId: String = "resource"): ReaderLaunch {
            val catalog = InMemoryDownloadCatalogRepository()
            val artifact = CompletedDownloadArtifact(stored, "managed/original", stored.totalBytes, 42)
            catalog.saveTask(DownloadTask("task", stored, DownloadTaskStatus.Completed,
                stored.totalBytes, artifact = artifact))
            return ReaderLaunchCoordinator(catalog, FailingMetadata(AppErrorKind.NetworkUnavailable))
                .prepare(context, requestedResourceId)
        }

        val otherResource = descriptor().copy(
            identity = descriptor().identity.copy(resourceId = "other-resource"),
        )
        assertIs<ReaderLaunchUnavailable>(decision(otherResource))
        for (candidate in listOf(
            descriptor(format = "pdf").copy(readerType = DownloadReaderType.Pdf,
                source = DownloadSource("/api/assets/asset", "application/pdf", 10)),
            descriptor(format = "cbz").copy(readerType = DownloadReaderType.Comic,
                source = DownloadSource("/api/assets/asset", "application/vnd.comicbook+zip", 10)),
            descriptor(format = "mp3").copy(readerType = DownloadReaderType.Audio,
                source = DownloadSource("/api/assets/asset", "audio/mpeg", 10)),
        )) {
            assertIs<ReaderLaunchUnavailable>(decision(candidate))
        }
    }

    @Test fun successfulDescriptorResponseStillRejectsAStaleLocalRevision(): Unit = runBlocking {
        val current = descriptor().copy(source = descriptor().source.copy(sourceModifiedAtMillis = 2))
        val stale = descriptor().copy(source = descriptor().source.copy(sourceModifiedAtMillis = 1))
        val artifact = CompletedDownloadArtifact(stale, "managed/stale", 10, 42)
        val catalog = InMemoryDownloadCatalogRepository()
        catalog.saveTask(DownloadTask("stale", stale, DownloadTaskStatus.Completed, 10, artifact = artifact))

        assertIs<ReaderLaunchDownload>(
            ReaderLaunchCoordinator(catalog, Metadata(current)).prepare(context, "resource"),
        )
    }

    @Test fun coverVariantsDoNotBlockReadingButCannotEscapeTheApi(): Unit = runBlocking {
        val cover = "/api/books/book/cover?size=medium&v=42"
        val publication = descriptor().copy(coverApiPath = cover)
        val launch = ReaderLaunchCoordinator(InMemoryDownloadCatalogRepository(), Metadata(publication))
            .prepare(context, "resource")
        assertEquals(cover, assertIs<ReaderLaunchDownload>(launch).descriptor.coverApiPath)
        for (unsafe in listOf("https://other.example/cover", "/api/../cover?size=small",
            "/api/books/book/cover#fragment", "/api/books/book/cover?size=small\n")) {
            assertFailsWith<IllegalArgumentException> { publication.copy(coverApiPath = unsafe) }
        }
        assertFailsWith<IllegalArgumentException> { publication.source.copy(apiPath = "/api/assets/asset?download=1") }
    }

    @Test fun pdfAndComicRemainStreamingWithoutImplicitDownload(): Unit = runBlocking {
        val pdf = descriptor(format = "pdf").copy(
            readerType = DownloadReaderType.Pdf,
            source = DownloadSource("/api/assets/asset", "application/pdf", 10),
        )
        val comic = descriptor(format = "cbz").copy(
            readerType = DownloadReaderType.Comic,
            source = DownloadSource("/api/assets/asset", "application/vnd.comicbook+zip", 10),
        )
        assertIs<ReaderLaunchStream>(ReaderLaunchCoordinator(InMemoryDownloadCatalogRepository(), Metadata(pdf))
            .prepare(context, "resource"))
        assertIs<ReaderLaunchStream>(ReaderLaunchCoordinator(InMemoryDownloadCatalogRepository(), Metadata(comic))
            .prepare(context, "resource"))
        assertFailsWith<IllegalArgumentException> { ReaderLaunchStream(descriptor()) }
        assertFailsWith<IllegalArgumentException> {
            ReaderLaunchStream(pdf.copy(readerType = DownloadReaderType.Reflowable))
        }
        assertFailsWith<IllegalArgumentException> {
            ReaderLaunchStream(comic.copy(readerType = DownloadReaderType.Pdf))
        }
    }

    @Test fun knownLocalEngineLimitsDoNotStartPointlessDownloads() = runBlocking {
        val largeText = descriptor(limit, "txt")
        val coordinator = ReaderLaunchCoordinator(InMemoryDownloadCatalogRepository(), Metadata(largeText))
        assertEquals(ReaderErrorCode.OutOfMemoryRisk,
            assertIs<ReaderLaunchUnavailable>(coordinator.prepare(context, "resource")).code)
    }

    @Test fun observingAnIndependentDownloadCannotOpenADifferentRevision() = runBlocking {
        val expected = descriptor()
        val changed = expected.copy(source = expected.source.copy(sourceModifiedAtMillis = 2))
        val artifact = CompletedDownloadArtifact(changed, "managed/original", 10, 42)
        val catalog = InMemoryDownloadCatalogRepository()
        catalog.saveTask(DownloadTask("task", changed, DownloadTaskStatus.Completed, 10, artifact = artifact))
        val coordinator = ReaderLaunchCoordinator(catalog, Metadata(expected))
        assertIs<ReaderLaunchDownload>(coordinator.prepare(context, "resource"))
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
