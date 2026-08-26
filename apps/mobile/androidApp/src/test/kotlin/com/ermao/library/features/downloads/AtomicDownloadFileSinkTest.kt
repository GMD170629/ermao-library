package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.infrastructure.AtomicDownloadFileSink
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadArtifactKind
import com.ermao.library.shared.modules.downloads.DownloadBundleMemberSinkRequest
import com.ermao.library.shared.modules.downloads.DownloadBundleSinkRequest
import com.ermao.library.shared.modules.downloads.DownloadSinkRequest
import java.nio.file.Files
import kotlin.test.assertContentEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest
import org.junit.Test

class AtomicDownloadFileSinkTest {
    @Test
    fun originalPageSetPublishesOnlyAfterEveryOriginalPageIsVerified() = runTest {
        val root = Files.createTempDirectory("download-page-set-test").toFile()
        try {
            val sink = AtomicDownloadFileSink(root)
            val first = pngBytes(1)
            val second = pngBytes(2)
            val bundle = sink.beginBundle(
                DownloadBundleSinkRequest(
                    namespace = DownloadNamespace("server", "user", 1),
                    taskId = "task",
                    resourceId = "resource",
                    artifactId = "page-set:resource",
                    artifactKind = DownloadArtifactKind.OriginalPageSet,
                    memberCount = 2,
                    expectedTotalBytes = (first.size + second.size).toLong(),
                ),
            )
            bundle.beginMember(DownloadBundleMemberSinkRequest("page-1", 0, "image/png", first.size.toLong())).also {
                it.write(first)
                it.commit(first.size.toLong())
            }
            assertFalse(root.walkTopDown().any { it.name == "bundle.json" })
            bundle.beginMember(DownloadBundleMemberSinkRequest("page-2", 1, "image/png", second.size.toLong())).also {
                it.write(second)
                it.commit(second.size.toLong())
            }

            val reference = bundle.commit()
            val directory = checkNotNull(sink.resolveLocalReference(reference))

            assertTrue(directory.isDirectory)
            assertTrue(directory.resolve("bundle.json").isFile)
            assertTrue(sink.hasLocalArtifact(reference))
            assertFalse(root.walkTopDown().any { it.name.endsWith(".part") })
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun cancelledOriginalPageSetNeverLeavesACompletedBundle() = runTest {
        val root = Files.createTempDirectory("download-page-set-cancel-test").toFile()
        try {
            val sink = AtomicDownloadFileSink(root)
            val page = pngBytes(1)
            val bundle = sink.beginBundle(
                DownloadBundleSinkRequest(
                    namespace = DownloadNamespace("server", "user", 1),
                    taskId = "task",
                    resourceId = "resource",
                    artifactId = "page-set:resource",
                    artifactKind = DownloadArtifactKind.OriginalPageSet,
                    memberCount = 2,
                    expectedTotalBytes = page.size.toLong() * 2,
                ),
            )
            bundle.beginMember(DownloadBundleMemberSinkRequest("page-1", 0, "image/png", page.size.toLong())).also {
                it.write(page)
                it.commit(page.size.toLong())
            }

            bundle.abort()

            assertFalse(root.walkTopDown().any { it.name == "bundle.json" || it.name.endsWith(".bundle") })
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun commitPublishesOnlyAfterExpectedBytesMatch() = runTest {
        val root = Files.createTempDirectory("download-sink-test").toFile()
        try {
            val sink = AtomicDownloadFileSink(root)
            val session = sink.begin(AndroidDownloadNamespace("server", "user", 1), "resource", "asset")
            session.write(byteArrayOf(1, 2))
            session.write(byteArrayOf(3, 4))

            val reference = session.commit(4)

            assertFalse(reference.startsWith('/'))
            assertContentEquals(byteArrayOf(1, 2, 3, 4), checkNotNull(sink.resolveLocalReference(reference)).readBytes())
            assertTrue(sink.hasLocalArtifact(reference))
            assertFalse(root.walkTopDown().any { it.extension == "part" })
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun mismatchedCommitDeletesPartialFile() = runTest {
        val root = Files.createTempDirectory("download-sink-failure-test").toFile()
        try {
            val session = AtomicDownloadFileSink(root).begin(
                AndroidDownloadNamespace("server", "user", 1),
                "resource",
                "asset",
            )
            session.write(byteArrayOf(1, 2))

            assertFailsWith<Exception> { session.commit(3) }
            assertTrue(root.walkTopDown().none { it.extension == "part" || it.extension == "bin" })
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun downloadRequestPublishesAfterLengthValidation() = runTest {
        val root = Files.createTempDirectory("download-sink-hash-test").toFile()
        try {
            val sink = AtomicDownloadFileSink(root)
            val session = sink.begin(
                DownloadSinkRequest(
                    namespace = DownloadNamespace("server", "user", 1),
                    taskId = "task",
                    resourceId = "resource",
                    assetId = "asset",
                    expectedTotalBytes = 4,
                    resumeFromBytes = 0,
                ),
            )
            session.write(byteArrayOf(1, 2, 3, 4))

            val reference = session.commit(4)

            assertContentEquals(byteArrayOf(1, 2, 3, 4), checkNotNull(sink.resolveLocalReference(reference)).readBytes())
            assertFalse(root.walkTopDown().any { it.extension == "part" })
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun localReferenceCannotEscapeManagedRoot() {
        val root = Files.createTempDirectory("download-sink-path-test").toFile()
        try {
            val sink = AtomicDownloadFileSink(root)
            assertTrue(sink.resolveLocalReference("../private.txt") == null)
            assertTrue(sink.resolveLocalReference("/private.txt") == null)
        } finally {
            root.deleteRecursively()
        }
    }

    private fun pngBytes(marker: Int): ByteArray = byteArrayOf(
        0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, marker.toByte(),
    )
}
