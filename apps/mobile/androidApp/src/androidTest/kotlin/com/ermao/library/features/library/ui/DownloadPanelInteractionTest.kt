package com.ermao.library.features.library.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.R
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.library.application.DownloadPanelScope
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.shared.modules.downloads.DownloadManagementAction
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class DownloadPanelInteractionTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun rowActionsPauseResumeRetryAndValidateOpenWithoutDeleting() {
        val resources = listOf("running", "paused", "failed", "done").map(::resource)
        val records = mapOf(
            "running" to record("running", AndroidDownloadStatus.Downloading),
            "paused" to record("paused", AndroidDownloadStatus.Paused),
            "failed" to record("failed", AndroidDownloadStatus.FailedRetryable),
            "done" to record("done", AndroidDownloadStatus.Completed),
        )
        val actions = mutableListOf<Pair<DownloadManagementAction, Set<String>>>()
        var opened: String? = null
        show(resources, records, actions) { opened = it }
        for (id in listOf("running", "paused", "failed", "done")) {
            compose.onNodeWithTag("download-resource-status-$id").assertIsDisplayed()
            compose.onNodeWithTag("download-resource-primary-$id").performClick()
        }
        compose.runOnIdle {
            assertEquals(listOf(
                DownloadManagementAction.Pause to setOf("running"),
                DownloadManagementAction.Resume to setOf("paused"),
                DownloadManagementAction.Retry to setOf("failed"),
                DownloadManagementAction.Open to setOf("done"),
            ), actions)
            assertEquals(null, opened)
        }
        compose.onNodeWithTag("download-resource-more-done").performClick()
        compose.onNodeWithText(context.getString(R.string.downloads_remove_action)).performClick()
        compose.onNodeWithText(context.getString(R.string.downloads_remove_title)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.cancel_action)).performClick()
        compose.runOnIdle { assertEquals(4, actions.size) }
    }

    @Test
    fun mixedSelectionDownloadsOnlyEligibleItemsAndClearsOnExit() {
        val actions = mutableListOf<Pair<DownloadManagementAction, Set<String>>>()
        show(listOf(resource("new"), resource("done")), mapOf("done" to record("done", AndroidDownloadStatus.Completed)), actions)
        compose.onNodeWithTag("download-selection-enter").performClick()
        compose.onNodeWithTag("download-batch-primary").assertIsNotEnabled()
        compose.onNodeWithTag("download-selection-all").performClick()
        compose.onNodeWithText(context.getString(R.string.multi_download_batch_download, 1)).assertIsDisplayed()
        compose.onNodeWithTag("download-batch-primary").performClick()
        compose.runOnIdle { assertEquals(listOf(DownloadManagementAction.Download to setOf("new")), actions) }
        compose.onNodeWithTag("download-selection-cancel").performClick()
        compose.onNodeWithTag("download-selection-enter").performClick()
        compose.onNodeWithTag("download-batch-primary").assertIsNotEnabled()
    }

    private fun show(
        resources: List<ResourceContent>,
        records: Map<String, AndroidDownloadRecord>,
        actions: MutableList<Pair<DownloadManagementAction, Set<String>>>,
        onOpen: (String) -> Unit = {},
    ) {
        val state = WorkDetailUiState(
            content = BookDetailContent(
                book = BookCard("book", "Download panel", "", "", null),
                description = null, resources = resources, selectedResourceId = null,
                seriesId = null, seriesName = null, authorFacetId = null, tags = emptyList(),
            ),
            multiDownloadScope = DownloadPanelScope.Book,
            multiDownloadRootNodeId = "root",
            multiDownloadDescendantResourceIdsByNodeId = mapOf("root" to resources.map { it.id }.toSet()),
            multiDownloadResources = resources,
        )
        compose.setContent {
            WarmPageTheme(darkTheme = false) {
                MultiDownloadSheet(
                    state = state, recordsByResource = records, onDismiss = {}, onRetryTree = {},
                    onToggleFolder = {}, onEnsureFolderLoaded = {},
                    onExecuteAction = { action, ids, _, complete ->
                        actions += action to ids
                        complete(emptyList())
                    },
                    onOpenDownloaded = { onOpen(it.resourceId) },
                )
            }
        }
    }

    private fun resource(id: String) = ResourceContent(
        id = id, title = id, format = "EPUB", sizeBytes = 1_000,
        progressPercent = null, readable = true, selected = false,
    )

    private fun record(id: String, status: AndroidDownloadStatus) = AndroidDownloadRecord(
        taskId = id, namespace = AndroidDownloadNamespace("server", "user", 1), bookId = "book",
        bookTitle = "Download panel", author = "", coverUrl = "", resourceId = id, resourceTitle = id,
        format = "EPUB", readerType = "reflowable", assetId = id, sourceApiPath = "/api/test",
        sourceMimeType = "application/epub+zip", expectedBytes = 1_000, transferredBytes = 400,
        status = status, verified = status == AndroidDownloadStatus.Completed,
        localReference = if (status == AndroidDownloadStatus.Completed) "test/$id.epub" else null,
        createdAtEpochMillis = 1, updatedAtEpochMillis = 1,
    )
}
