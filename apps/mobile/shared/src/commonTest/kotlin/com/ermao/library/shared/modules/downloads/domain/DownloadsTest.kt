package com.ermao.library.shared.modules.downloads.domain

import com.ermao.library.shared.modules.reader.readerSafetyComicExpandedMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyComicPageMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyComicPageMaxCount
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class DownloadsTest {
    @Test
    fun completedCatalogIsNamespaceScopedAndGroupedBookResourceAsset() {
        val primary = namespace("server-a", "user-a", 3)
        val artifacts = listOf(
            artifact(primary, "book-1", "resource-2", "asset-2", "星海纪事", "林青", "终章", 30, sortOrder = 2),
            artifact(primary, "book-1", "resource-1", "asset-1", "星海纪事", "林青", "上册", 20, sortOrder = 1),
            artifact(primary, "book-1", "resource-1", "asset-0", "星海纪事", "林青", "上册", 10, sortOrder = 1),
            artifact(primary, "book-2", "resource-3", "asset-3", "Quiet Pages", "Mira", "Volume One", 40),
            artifact(namespace("server-a", "user-b", 3), "book-1", "private", "asset-private", "星海纪事", "林青", "私有", 10),
        )

        val all = completedDownloadsByBook(primary, artifacts)
        assertEquals(listOf("book-2", "book-1"), all.map { it.bookId })
        val firstBook = all.first { it.bookId == "book-1" }
        assertEquals(listOf("resource-1", "resource-2"), firstBook.resources.map { it.resourceId })
        assertEquals(listOf("asset-0", "asset-1", "asset-2"), firstBook.artifacts.map { it.identity.assetId })
        assertEquals(60, firstBook.totalBytes)
        assertEquals(listOf("book-1"), completedDownloadsByBook(primary, artifacts, "林青").map { it.bookId })
        assertEquals(listOf("book-1"), completedDownloadsByBook(primary, artifacts, "终章").map { it.bookId })
        assertEquals(listOf("book-2"), completedDownloadsByBook(primary, artifacts, "quiet").map { it.bookId })
    }

    @Test
    fun resourcesSortByExplicitOrderAndAssetsSortByStableAssetId() {
        val ns = namespace("server", "user", 1)
        val resources = listOf(
            artifact(ns, "book", "resource-z", "asset-z", "Book", null, "Z", 10, sortOrder = 2),
            artifact(ns, "book", "resource-a", "asset-b", "Book", null, "A", 10, sortOrder = 1),
            artifact(ns, "book", "resource-a", "asset-a", "Book", null, "A", 10, sortOrder = 1),
        )

        val book = completedDownloadsByBook(ns, resources).single()
        assertEquals(listOf("resource-a", "resource-z"), book.resources.map { it.resourceId })
        assertEquals(listOf("asset-a", "asset-b", "asset-z"), book.artifacts.map { it.identity.assetId })
        assertEquals(book.resources.flatMap { it.artifacts }, book.artifacts)
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
        val descriptor = descriptor(namespace("server", "user", 1), "book", "resource", "asset", 10)
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

    @Test
    fun mediaSourceAcceptsOnlyResourceOrAssetApiRoutes() {
        assertFailsWith<IllegalArgumentException> {
            DownloadSource("/api/volumes/resource/file", "application/epub+zip", 10)
        }
        assertFailsWith<IllegalArgumentException> {
            DownloadSource("/api/assets/asset?download=true", "application/epub+zip", 10)
        }
        assertFailsWith<IllegalArgumentException> {
            DownloadSource("/api/unrelated/file", "application/zip", 10)
        }
    }

    @Test
    fun originalPageSetEnforcesGeneratedComicAdmission() {
        fun page(index: Int, mimeType: String = "image/png", bytes: Long = 1) = DownloadBundleMember(
            assetId = "page-$index",
            sequenceIndex = index,
            source = DownloadSource("/api/assets/page-$index", mimeType, bytes),
        )
        fun descriptorFor(members: List<DownloadBundleMember>) = DownloadDescriptor(
            identity = DownloadIdentity(namespace("server", "user", 1), "book", "resource", "page-set"),
            bookTitle = "Book",
            bookAuthor = null,
            coverApiPath = null,
            resourceTitle = "Pages",
            format = "image_dir",
            readerType = DownloadReaderType.Comic,
            source = members.first().source,
            artifactKind = DownloadArtifactKind.OriginalPageSet,
            members = members,
        )

        assertFailsWith<IllegalArgumentException> { descriptorFor(listOf(page(0, "image/svg+xml"))) }
        assertFailsWith<IllegalArgumentException> {
            descriptorFor(listOf(page(0, bytes = readerSafetyComicPageMaxBytes() + 1)))
        }
        assertFailsWith<IllegalArgumentException> {
            descriptorFor((0..readerSafetyComicPageMaxCount().toInt()).map(::page))
        }
        val fullPages = readerSafetyComicExpandedMaxBytes() / readerSafetyComicPageMaxBytes()
        val members = (0 until fullPages.toInt()).map { page(it, bytes = readerSafetyComicPageMaxBytes()) } +
            page(fullPages.toInt(), bytes = 1)
        assertFailsWith<IllegalArgumentException> { descriptorFor(members) }
    }

    private fun namespace(server: String, user: String, version: Long) = DownloadNamespace(server, user, version)

    private fun descriptor(
        namespace: DownloadNamespace,
        bookId: String,
        resourceId: String,
        assetId: String,
        bytes: Long,
        title: String = bookId,
        author: String? = null,
        resourceTitle: String = resourceId,
        sortOrder: Int? = null,
    ) = DownloadDescriptor(
        identity = DownloadIdentity(namespace, bookId, resourceId, assetId),
        bookTitle = title,
        bookAuthor = author,
        coverApiPath = "/api/books/$bookId/cover",
        resourceTitle = resourceTitle,
        format = "epub",
        readerType = DownloadReaderType.Reflowable,
        source = DownloadSource("/api/assets/$assetId", "application/epub+zip", bytes),
        resourceSortOrder = sortOrder,
    )

    private fun artifact(
        namespace: DownloadNamespace,
        bookId: String,
        resourceId: String,
        assetId: String,
        title: String,
        author: String?,
        resourceTitle: String,
        bytes: Long,
        sortOrder: Int? = null,
    ) = artifact(
        descriptor(namespace, bookId, resourceId, assetId, bytes, title, author, resourceTitle, sortOrder),
        bytes,
    )

    private fun artifact(descriptor: DownloadDescriptor, bytes: Long) = CompletedDownloadArtifact(
        descriptor = descriptor,
        localReference = "local://${descriptor.identity.assetId}",
        verifiedBytes = bytes,
        completedAtEpochMillis = 1,
    )
}
