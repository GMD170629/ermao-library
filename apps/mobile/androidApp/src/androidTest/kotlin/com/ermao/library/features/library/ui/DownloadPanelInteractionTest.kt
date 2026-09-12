package com.ermao.library.features.library.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.text.TextLayoutResult
import android.graphics.Bitmap
import java.io.File
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class DownloadPanelInteractionTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun longTitlesClipWithoutEllipsis() {
        val fontScale = context.resources.configuration.fontScale
        val bookTitle = "很长的图书名称，需要完整说明其身份与故事背景，且超过两行时支持展开查看所有内容".repeat(2)
        val longTitle = "番外：A very long English volume title 与超长中文标题".repeat(4)
        val resources = listOf(
            resource("done").copy(title = "$bookTitle 01"),
            resource("running").copy(title = "$bookTitle $longTitle"),
            resource("failed").copy(title = longTitle),
        )
        show(resources, mapOf(
            "done" to record("done", AndroidDownloadStatus.Completed),
            "running" to record("running", AndroidDownloadStatus.Downloading),
            "failed" to record("failed", AndroidDownloadStatus.FailedRetryable),
        ), mutableListOf(), bookTitle = bookTitle)
        for (id in listOf("done", "running", "failed")) {
            val results = mutableListOf<TextLayoutResult>()
            val titleNode = compose.onNodeWithTag("download-resource-title-$id", useUnmergedTree = true)
            titleNode.performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(results) }
            assertEquals(fontScale, results.single().layoutInput.density.fontScale, 0.01f)
            assertEquals(1, results.single().lineCount)
            assertFalse(results.single().isLineEllipsized(0))
            if (id != "done") {
                // The semantics layout reports the visible line rather than an
                // oversized intrinsic paragraph. The rest must remain hidden.
                assertTrue("Long title must have hidden trailing content: $id",
                    results.single().getLineEnd(0) < results.single().layoutInput.text.length)
            }
        }
        compose.onNodeWithTag("download-resource-primary-running").assertIsDisplayed()
        compose.onNodeWithTag("download-resource-primary-failed").assertIsDisplayed()
        compose.onNodeWithContentDescription("$bookTitle 01").assertIsDisplayed()
        compose.waitForIdle()
        if (InstrumentationRegistry.getArguments().getString("captureDownloadPanelScreenshots") == "true") {
            val output = File(context.getExternalFilesDir(null), "download-panel-$fontScale.png")
            val bitmap = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
            output.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
        }


    }

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
        for (id in listOf("running", "paused", "failed")) {
            compose.onNodeWithTag("download-resource-status-$id", useUnmergedTree = true).assertIsDisplayed()
            compose.onNodeWithTag("download-resource-primary-$id").performClick()
        }
        compose.onNodeWithTag("download-resource-status-done", useUnmergedTree = true).assertIsDisplayed()
        compose.onNodeWithTag("download-resource-primary-done").assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.work_download_open_offline)).assertDoesNotExist()
        compose.onNodeWithContentDescription("done").performClick()
        compose.runOnIdle {
            assertEquals(listOf(
                DownloadManagementAction.Pause to setOf("running"),
                DownloadManagementAction.Resume to setOf("paused"),
                DownloadManagementAction.Retry to setOf("failed"),
                DownloadManagementAction.Open to setOf("done"),
            ), actions)
            assertEquals(null, opened)
        }
        compose.onNodeWithTag("download-resource-remove-done").performClick()
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
        bookTitle: String = "Download panel",
        onOpen: (String) -> Unit = {},
    ) {
        val state = WorkDetailUiState(
            content = BookDetailContent(
                book = BookCard("book", bookTitle, "", "", null),
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
