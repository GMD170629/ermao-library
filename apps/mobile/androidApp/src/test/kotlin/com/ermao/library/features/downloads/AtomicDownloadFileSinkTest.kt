package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.infrastructure.AtomicDownloadFileSink
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import java.nio.file.Files
import kotlin.test.assertContentEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest
import org.junit.Test

class AtomicDownloadFileSinkTest {
    @Test
    fun commitPublishesOnlyAfterExpectedBytesMatch() = runTest {
        val root = Files.createTempDirectory("download-sink-test").toFile()
        try {
            val sink = AtomicDownloadFileSink(root)
            val session = sink.begin(AndroidDownloadNamespace("server", "user", 1), "volume", "fingerprint")
            session.write(byteArrayOf(1, 2))
            session.write(byteArrayOf(3, 4))

            val reference = session.commit(4)

            assertFalse(reference.startsWith('/'))
            assertContentEquals(byteArrayOf(1, 2, 3, 4), checkNotNull(sink.resolveLocalReference(reference)).readBytes())
            assertTrue(sink.isVerifiedLocalArtifact(reference, 4))
            assertFalse(sink.isVerifiedLocalArtifact(reference, 5))
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
                "volume",
                "fingerprint",
            )
            session.write(byteArrayOf(1, 2))

            assertFailsWith<Exception> { session.commit(3) }
            assertTrue(root.walkTopDown().none { it.extension == "part" || it.extension == "bin" })
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
}
