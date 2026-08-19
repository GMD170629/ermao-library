package com.ermao.library.features.workmanagement.application

import kotlin.test.assertEquals
import kotlin.test.assertNull
import org.junit.Test

class DownloadOwnershipRewriteTest {
    @Test
    fun splitUsesServerTargetVersionAsImplicitLibraryVersion() {
        val rewrite = downloadOwnershipRewriteForStructuralMove(
            targetWorkId = "work-target",
            targetVersionId = "version-target",
            targetWorkTitle = "Split Work",
            targetWorkAuthor = "Author",
            targetCoverApiPath = "/api/works/work-target/cover",
        )

        assertEquals("work-target", rewrite?.targetWorkId)
        assertEquals("version-target", rewrite?.targetVersionId)
        assertEquals(STRUCTURAL_MOVE_VERSION_SOURCE_KEY, rewrite?.targetVersionSourceKey)
        assertNull(rewrite?.targetVersionSourceName)
        assertNull(rewrite?.targetVersionCompleted)
    }

    @Test
    fun missingTargetWorkOrVersionLeavesLocalOwnershipUnchanged() {
        assertNull(
            downloadOwnershipRewriteForStructuralMove(
                targetWorkId = "work-target",
                targetVersionId = null,
                targetWorkTitle = "Split Work",
                targetWorkAuthor = null,
                targetCoverApiPath = null,
            ),
        )
        assertNull(
            downloadOwnershipRewriteForStructuralMove(
                targetWorkId = null,
                targetVersionId = "version-target",
                targetWorkTitle = "Split Work",
                targetWorkAuthor = null,
                targetCoverApiPath = null,
            ),
        )
        assertNull(
            downloadOwnershipRewriteForStructuralMove(
                targetWorkId = "  ",
                targetVersionId = "version-target",
                targetWorkTitle = "Split Work",
                targetWorkAuthor = null,
                targetCoverApiPath = null,
            ),
        )
    }
}
