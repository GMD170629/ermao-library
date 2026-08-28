package com.ermao.library.shared.modules.downloads.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class MultiDownloadSelectionTest {
    private val resources = listOf(
        MultiDownloadResourceState("new", MultiDownloadEligibility.Enqueue),
        MultiDownloadResourceState("paused", MultiDownloadEligibility.Resume),
        MultiDownloadResourceState("failed", MultiDownloadEligibility.Retry),
        MultiDownloadResourceState("active", MultiDownloadEligibility.Active),
        MultiDownloadResourceState("done", MultiDownloadEligibility.Completed),
    ).associateBy(MultiDownloadResourceState::resourceId)

    @Test
    fun batchIntentPolicyDoesNotReportActiveCompletedOrRejectedTasksAsAccepted() {
        val result = DownloadBatchResult(listOf(
            DownloadBatchPolicy.decide("new", null, null, false),
            DownloadBatchPolicy.decide("queued", DownloadTaskStatus.Queued, null, false),
            DownloadBatchPolicy.decide("paused", DownloadTaskStatus.Paused, null, false),
            DownloadBatchPolicy.decide("retry", DownloadTaskStatus.FailedRetryable, "NETWORK", false),
            DownloadBatchPolicy.decide("space", DownloadTaskStatus.InsufficientSpace, "SPACE", false),
            DownloadBatchPolicy.decide("active", null, null, true),
            DownloadBatchPolicy.decide("complete", DownloadTaskStatus.Completed, null, false),
            DownloadBatchPolicy.decide("terminal", DownloadTaskStatus.FailedTerminal, "DENIED", false),
        ))
        assertEquals(listOf("new", "queued", "paused", "retry", "space"), result.requestedResourceIds)
        assertEquals(5, result.succeededCount)
        assertEquals(setOf("terminal"), result.failedResourceIds)
        assertEquals("DENIED", result.results.last().failureCode)
    }

    @Test
    fun directorySelectionIncludesOnlySmartBatchEligibleResources() {
        val state = MultiDownloadSelectionState().toggleDirectory(resources.keys, resources)

        assertEquals(setOf("new", "paused", "failed"), state.selectedResourceIds)
        assertEquals(
            MultiDownloadSelectionMark.Selected,
            state.directoryMark(resources.keys, resources),
        )
    }

    @Test
    fun directorySelectionSupportsMixedAndClearStates() {
        val partial = MultiDownloadSelectionState(selectedResourceIds = setOf("new"))
        assertEquals(MultiDownloadSelectionMark.Mixed, partial.directoryMark(resources.keys, resources))

        val selected = partial.toggleDirectory(resources.keys, resources)
        assertEquals(setOf("new", "paused", "failed"), selected.selectedResourceIds)

        val cleared = selected.toggleDirectory(resources.keys, resources)
        assertTrue(cleared.selectedResourceIds.isEmpty())
    }

    @Test
    fun unselectableResourceCannotBeSelected() {
        val state = MultiDownloadSelectionState().toggleResource(requireNotNull(resources["done"]))
        assertFalse("done" in state.selectedResourceIds)
    }

    @Test
    fun batchSummaryClassifiesSelectedIntent() {
        val summary = summarizeDownloadBatch(setOf("new", "paused", "failed"), resources)
        assertEquals(3, summary.selectedCount)
        assertEquals(1, summary.enqueueCount)
        assertEquals(1, summary.resumeCount)
        assertEquals(1, summary.retryCount)
    }
}
