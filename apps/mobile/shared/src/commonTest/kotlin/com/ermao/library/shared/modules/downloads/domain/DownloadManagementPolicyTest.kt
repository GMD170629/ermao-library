package com.ermao.library.shared.modules.downloads.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DownloadManagementPolicyTest {
    private fun resource(
        id: String,
        status: DownloadTaskStatus? = null,
        verified: Boolean = false,
        active: Boolean = false,
        available: Boolean = true,
    ): DownloadManagementResource = DownloadManagementPolicy.project(
        DownloadManagementItem(id, status, verified, active, available),
    )

    @Test
    fun primaryButtonOpensVerifiedCopiesAndControlsEligibleTransfers() {
        assertEquals(DownloadManagementAction.Download, resource("new").primaryAction)
        assertEquals(DownloadManagementAction.Open, resource("done", DownloadTaskStatus.Completed, verified = true).primaryAction)
        assertEquals(DownloadManagementAction.Resume, resource("paused", DownloadTaskStatus.Paused).primaryAction)
        assertEquals(DownloadManagementAction.Retry, resource("failed", DownloadTaskStatus.FailedRetryable).primaryAction)
        assertEquals(DownloadManagementAction.Retry, resource("invalid", DownloadTaskStatus.Completed).primaryAction)
        assertEquals(DownloadManagementAction.Pause, resource("running", DownloadTaskStatus.Downloading, active = true).primaryAction)
        assertEquals(DownloadManagementAction.Pause, resource("queued", DownloadTaskStatus.Queued).primaryAction)
        assertEquals(null, resource("offline", available = false).primaryAction)
    }

    @Test
    fun bothPlatformsReceiveTheSameActionsForEveryPersistedStatus() {
        val cases = listOf(
            Triple(DownloadTaskStatus.Queued, DownloadManagementStatus.Queued, DownloadManagementAction.Pause),
            Triple(DownloadTaskStatus.Downloading, DownloadManagementStatus.Downloading, DownloadManagementAction.Pause),
            Triple(DownloadTaskStatus.Paused, DownloadManagementStatus.Paused, DownloadManagementAction.Resume),
            Triple(DownloadTaskStatus.WaitingForWifi, DownloadManagementStatus.Paused, DownloadManagementAction.Resume),
            Triple(DownloadTaskStatus.InsufficientSpace, DownloadManagementStatus.FailedRetryable, DownloadManagementAction.Retry),
            Triple(DownloadTaskStatus.FailedRetryable, DownloadManagementStatus.FailedRetryable, DownloadManagementAction.Retry),
            Triple(DownloadTaskStatus.Completed, DownloadManagementStatus.Completed, DownloadManagementAction.Open),
        )
        cases.forEach { (stored, displayed, action) ->
            val actual = resource(stored.name, stored, verified = true)
            assertEquals(displayed, actual.status)
            assertEquals(action, actual.primaryAction)
            assertEquals(setOf(action, DownloadManagementAction.Remove), actual.actions)
        }
        listOf(DownloadTaskStatus.FailedTerminal, DownloadTaskStatus.Cancelled).forEach {
            assertEquals(setOf(DownloadManagementAction.Remove), resource(it.name, it).actions)
        }
        assertEquals(setOf(DownloadManagementAction.Download), resource("new").actions)
    }

    @Test
    fun invalidCompletedArtifactIsNeverShownAsDownloadedOrOpened() {
        val invalid = resource("invalid", DownloadTaskStatus.Completed)
        assertEquals(DownloadManagementStatus.InvalidLocal, invalid.status)
        assertEquals(DownloadManagementAction.Retry, invalid.primaryAction)
        assertFalse(DownloadManagementAction.Open in invalid.actions)
        assertTrue(DownloadManagementAction.Remove in invalid.actions)
    }

    @Test
    fun catalogIntegrityFailureRetainsRetryWithoutAllowingTerminalFailuresInGeneral() {
        val invalid = DownloadManagementPolicy.project(DownloadManagementItem(
            "missing", DownloadTaskStatus.FailedTerminal, verified = false,
            active = false, available = true, failureCode = "DOWNLOAD_LOCAL_FILE_INVALID",
        ))
        assertEquals(DownloadManagementStatus.InvalidLocal, invalid.status)
        assertEquals(setOf(DownloadManagementAction.Retry, DownloadManagementAction.Remove), invalid.actions)
        assertEquals(setOf(DownloadManagementAction.Remove), resource("denied", DownloadTaskStatus.FailedTerminal).actions)
    }

    @Test
    fun activeTransferSuppressesDuplicateStartEvenBeforeFirstCatalogEvent() {
        val active = resource("starting", active = true)
        assertEquals(DownloadManagementStatus.Downloading, active.status)
        assertEquals(setOf(DownloadManagementAction.Pause, DownloadManagementAction.Remove), active.actions)
        val retrying = resource("retrying", DownloadTaskStatus.FailedRetryable, active = true)
        assertEquals(active.actions, retrying.actions)
    }

    @Test
    fun unavailableRemoteMetadataDoesNotRemoveLocalActions() {
        val local = resource("local", DownloadTaskStatus.Completed, verified = true, available = false)
        assertEquals(setOf(DownloadManagementAction.Open, DownloadManagementAction.Remove), local.actions)
        val paused = resource("paused", DownloadTaskStatus.Paused, available = false)
        assertEquals(setOf(DownloadManagementAction.Remove), paused.actions)
        val missing = resource("missing", available = false)
        assertTrue(missing.actions.isEmpty())
        assertFalse(missing.selectable)
    }

    @Test
    fun folderSelectionIncludesCompletedFilesAndPreservesOtherFolders() {
        val resources = listOf(
            resource("new"), resource("done", DownloadTaskStatus.Completed, verified = true),
            resource("outside"), resource("unavailable", available = false),
        )
        val children = setOf("new", "done", "unavailable")
        val selected = DownloadManagementPolicy.toggleSelection(setOf("outside"), children, resources)
        assertEquals(setOf("new", "done", "outside"), selected)
        assertEquals(MultiDownloadSelectionMark.Selected, DownloadManagementPolicy.selectionMark(selected, children, resources))
        assertEquals(MultiDownloadSelectionMark.Mixed, DownloadManagementPolicy.selectionMark(setOf("done"), children, resources))
        assertEquals(setOf("outside"), DownloadManagementPolicy.toggleSelection(selected, children, resources))
    }

    @Test
    fun currentFactsDetermineActionCountsAndTargetsAfterStatusChanges() {
        val selected = setOf("new", "paused", "retry", "done", "removed")
        val resources = listOf(
            resource("new", active = true), resource("paused", DownloadTaskStatus.Paused),
            resource("retry", DownloadTaskStatus.FailedRetryable),
            resource("done", DownloadTaskStatus.Completed, verified = true),
        )
        fun applicable(action: DownloadManagementAction) = DownloadManagementPolicy.applicable(action, selected, resources)
        assertTrue(applicable(DownloadManagementAction.Download).isEmpty())
        assertEquals(listOf("new"), applicable(DownloadManagementAction.Pause))
        assertEquals(listOf("paused"), applicable(DownloadManagementAction.Resume))
        assertEquals(listOf("retry"), applicable(DownloadManagementAction.Retry))
        assertEquals(listOf("done", "new", "paused", "retry"), applicable(DownloadManagementAction.Remove))
        assertEquals(selected - "removed", DownloadManagementPolicy.toggleSelection(selected, emptySet(), resources))
    }

    @Test
    fun hiddenAndOutOfScopeResourcesCannotBecomeBatchTargets() {
        val resources = listOf(resource("inside"))
        assertEquals(listOf("inside"), DownloadManagementPolicy.applicable(
            DownloadManagementAction.Download, setOf("inside", "other-book"), resources,
        ))
        assertEquals(MultiDownloadSelectionMark.Unselected, DownloadManagementPolicy.selectionMark(
            setOf("other-book"), setOf("unknown"), resources,
        ))
    }
}
