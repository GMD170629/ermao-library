package com.ermao.library.features.reader.infrastructure

import java.nio.file.Files
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.Test

class AndroidReaderPublicationStoreTest {
    @Test
    fun removesOnlyAttributedAutomaticReplicaAndPartial() {
        val root = Files.createTempDirectory("reader-auto-migration").toFile()
        try {
            val stem = sha256("resource\u0000asset")
            val replica = root.resolve("$stem.epub").apply { writeText("automatic") }
            val partial = root.resolve(".$stem.epub.123.download").apply { writeText("partial") }
            val imported = root.resolve("imported.epub").apply { writeText("local") }
            val another = root.resolve("another.epub").apply { writeText("another account") }
            removeAutomaticReaderReplica(root, "resource", "asset")
            assertFalse(replica.exists())
            assertFalse(partial.exists())
            assertTrue(imported.exists())
            assertTrue(another.exists())
        } finally { root.deleteRecursively() }
    }

    @Test
    fun comicArchivePathValidationAllowsStandardDirectoryEntries() {
        assertTrue(isSafeComicArchiveEntryPath("chapter 01/", isDirectory = true))
        assertTrue(isSafeComicArchiveEntryPath("chapter 01/001.jpg", isDirectory = false))
    }

    @Test
    fun comicArchivePathValidationStillRejectsTraversalAndMalformedSegments() {
        assertFalse(isSafeComicArchiveEntryPath("../001.jpg", isDirectory = false))
        assertFalse(isSafeComicArchiveEntryPath("chapter//001.jpg", isDirectory = false))
        assertFalse(isSafeComicArchiveEntryPath("/chapter/001.jpg", isDirectory = false))
        assertFalse(isSafeComicArchiveEntryPath("chapter\\001.jpg", isDirectory = false))
    }

    @Test
    fun comicArchiveEntryHrefEncodesSpacesAndUnicodeWithoutFlatteningDirectories() {
        assertTrue(
            encodeComicArchiveEntryHref("001 第1话 残酷/001.jpg") ==
                "001%20%E7%AC%AC1%E8%AF%9D%20%E6%AE%8B%E9%85%B7/001.jpg",
        )
    }

}
