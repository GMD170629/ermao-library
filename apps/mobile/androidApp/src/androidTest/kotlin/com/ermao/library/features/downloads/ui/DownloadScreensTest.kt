package com.ermao.library.features.downloads.ui

import androidx.compose.runtime.mutableStateOf
import android.graphics.Bitmap
import java.io.File
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.R
import com.ermao.library.features.downloads.application.DownloadCenterUiState
import com.ermao.library.features.downloads.application.DownloadedBookUiState
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.downloads.model.DownloadedBookGroup
import com.ermao.library.features.downloads.model.DownloadedResourceGroup
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DownloadScreensTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun mixedLibraryNavigatesDirectlyToResourcesAndKeepsActionsScoped() {
        val done = sampleRecord().copy(bookTitle = "三体", author = "刘慈欣", resourceTitle = "三体")
        val running = done.copy(taskId = "running", resourceId = "running", assetId = "running",
            resourceTitle = "三体 II：黑暗森林", status = AndroidDownloadStatus.Downloading,
            verified = false, localReference = null, transferredBytes = 1269)
        val failed = running.copy(taskId = "failed", resourceId = "failed", assetId = "failed",
            resourceTitle = "三体 III：死神永生", status = AndroidDownloadStatus.FailedRetryable)
        val records = listOf(done, running, failed)
        val book = sampleBook(done).copy(title = "三体", author = "刘慈欣", resources = records.map {
            DownloadedResourceGroup(it.resourceId, it.resourceTitle, listOf(it))
        })
        val selected = mutableStateOf(false)
        val query = mutableStateOf("")
        val actions = mutableListOf<Pair<com.ermao.library.shared.modules.downloads.DownloadManagementAction, String>>()
        var opened = 0
        compose.setContent {
            WarmPageTheme {
                if (!selected.value) DownloadCenterScreen(
                    state = DownloadCenterUiState(isLoading = false, query = query.value, books = listOf(book), totalCompletedBytes = done.expectedBytes),
                    onBack = {}, onQueryChanged = { query.value = it }, onClearQuery = { query.value = "" },
                    onOpenBook = { selected.value = true }, onRetry = {},
                ) else DownloadedBookScreen(
                    state = DownloadedBookUiState(isLoading = false, book = book),
                    onBack = { selected.value = false }, onRetry = {}, onOpenResource = { opened++ },
                    onAction = { action, id ->
                        actions += action to id.resourceId
                        com.ermao.library.shared.modules.downloads.DownloadManagementResult(id.resourceId, action,
                            com.ermao.library.shared.modules.downloads.DownloadManagementOutcome.Completed)
                    },
                )
            }
        }
        compose.onNodeWithTag("downloads-search").performTextInput("三体")
        capture("download-center")
        compose.onNodeWithTag("settings-row-book-book-1").performClick()
        compose.onNodeWithTag("download-resource-status-running", useUnmergedTree = true).assertIsDisplayed()
        compose.onNodeWithTag("download-resource-status-failed", useUnmergedTree = true).assertIsDisplayed()
        capture("download-book")
        compose.onNodeWithTag("settings-row-resource-running").performClick()
        compose.onNodeWithTag("settings-row-resource-failed").performClick()
        compose.runOnIdle { assertEquals(0, opened) }
        compose.onNodeWithTag("download-resource-primary-failed", useUnmergedTree = true).performClick()
        compose.waitForIdle()
        compose.runOnIdle { assertEquals("failed", actions.single().second) }
        compose.onNodeWithTag("download-resource-remove-resource-1", useUnmergedTree = true).performClick()
        compose.onNodeWithText(string(R.string.cancel_action)).performClick()
        compose.runOnIdle { assertEquals(1, actions.size) }
        compose.onNodeWithTag("settings-row-resource-asset-1").performClick()
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(1, opened) }
        compose.onNodeWithTag("warm-page-navigation").performClick()
        compose.onNodeWithTag("downloads-search").assertIsDisplayed()
        compose.runOnIdle { assertEquals("三体", query.value) }
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val directory = File(instrumentation.targetContext.getExternalFilesDir(null), "download-ui")
        directory.mkdirs()
        val bitmap = instrumentation.uiAutomation.takeScreenshot()
        File(directory, "$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
    }

    @Test
    fun emptyDownloadCenterKeepsSearchAndSecondaryNavigationVisible() {
        var backCount = 0
        val query = mutableStateOf("")

        compose.setContent {
            WarmPageTheme {
                DownloadCenterScreen(
                    state = DownloadCenterUiState(isLoading = false, query = query.value),
                    onBack = { backCount++ },
                    onQueryChanged = { query.value = it },
                    onClearQuery = { query.value = "" },
                    onOpenBook = {},
                    onRetry = {},



                )
            }
        }

        compose.onNodeWithTag("downloads-center").assertIsDisplayed()
        compose.onNodeWithTag("settings-page-scroll").assertIsDisplayed()
        compose.onNodeWithTag("downloads-search").assertIsDisplayed().performTextInput("missing")
        compose.onNodeWithTag("settings-empty").assertIsDisplayed()
        compose.onNodeWithTag("warm-page-navigation").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(1, backCount) }
    }

    @Test
    fun downloadCenterErrorUsesStandardRetryStateAndLoadingStateIsNotInteractive() {
        val state = mutableStateOf(DownloadCenterUiState(isLoading = true))
        var retryCount = 0

        compose.setContent {
            WarmPageTheme {
                DownloadCenterScreen(
                    state = state.value,
                    onBack = {},
                    onQueryChanged = {},
                    onClearQuery = {},
                    onOpenBook = {},
                    onRetry = { retryCount++ },



                )
            }
        }

        compose.onNodeWithTag("settings-loading").assertIsDisplayed()
        compose.onNodeWithTag("downloads-search").assertDoesNotExist()

        compose.runOnIdle {
            state.value = DownloadCenterUiState(
                isLoading = false,
                errorCode = "DOWNLOAD_CATALOG_UNAVAILABLE",
            )
        }
        compose.waitForIdle()
        compose.onNodeWithTag("settings-error").assertIsDisplayed()
        compose.onNodeWithText(string(R.string.retry_action))
            .assertIsDisplayed()
            .performClick()
        compose.runOnIdle { assertEquals(1, retryCount) }
    }

    @Test
    fun populatedDownloadCenterUsesNavigationRowsAndBookCallback() {
        val book = sampleBook()
        var openedBook: String? = null

        compose.setContent {
            WarmPageTheme {
                DownloadCenterScreen(
                    state = DownloadCenterUiState(
                        isLoading = false,
                        books = listOf(book),
                        totalCompletedBytes = book.totalBytes,
                    ),
                    onBack = {},
                    onQueryChanged = {},
                    onClearQuery = {},
                    onOpenBook = { openedBook = it },
                    onRetry = {},



                )
            }
        }

        compose.onNodeWithTag("settings-row-book-book-1")
            .assertIsDisplayed()
            .assertHasClickAction()
            .performClick()
        compose.runOnIdle { assertEquals("book-1", openedBook) }
    }

    @Test
    fun downloadedBookUsesSecondaryScaffoldAndResourceNavigationRows() {
        val record = sampleRecord()
        var openedAsset: String? = null
        compose.setContent {
            WarmPageTheme {
                DownloadedBookScreen(
                    state = DownloadedBookUiState(
                        isLoading = false,
                        book = sampleBook(record),
                    ),
                    onBack = {},
                    onRetry = {},
                    onAction = { action, id -> com.ermao.library.shared.modules.downloads.DownloadManagementResult(id.resourceId, action, com.ermao.library.shared.modules.downloads.DownloadManagementOutcome.Completed) },
                    onOpenResource = { openedAsset = it.assetId },
                )
            }
        }

        compose.onNodeWithTag("downloads-book").assertIsDisplayed()
        compose.onNodeWithTag("settings-page-scroll").assertIsDisplayed()
        compose.onNodeWithTag("settings-row-resource-asset-1")
            .assertIsDisplayed()
            .assertHasClickAction()
            .performClick()
        compose.runOnIdle { assertEquals("asset-1", openedAsset) }
    }

    @Test
    fun downloadedBookEmptyStateIsStableAndDoesNotExposeResourceRows() {
        compose.setContent {
            WarmPageTheme {
                DownloadedBookScreen(
                    state = DownloadedBookUiState(isLoading = false, book = null),
                    onBack = {},
                    onRetry = {},
                    onAction = { action, id -> com.ermao.library.shared.modules.downloads.DownloadManagementResult(id.resourceId, action, com.ermao.library.shared.modules.downloads.DownloadManagementOutcome.Completed) },
                    onOpenResource = {},
                )
            }
        }

        compose.onNodeWithTag("downloads-book").assertIsDisplayed()
        compose.onNodeWithTag("settings-empty").assertIsDisplayed()
        compose.onNodeWithTag("settings-row-resource-asset-1").assertDoesNotExist()
    }

    private fun sampleBook(record: AndroidDownloadRecord = sampleRecord()): DownloadedBookGroup =
        DownloadedBookGroup(
            bookId = "book-1",
            title = "The Sample Book",
            author = "Sample Author",
            coverUrl = "",
            resources = listOf(
                DownloadedResourceGroup(
                    resourceId = "resource-1",
                    title = "EPUB",
                    artifacts = listOf(record),
                ),
            ),
        )

    private fun sampleRecord(): AndroidDownloadRecord = AndroidDownloadRecord(
        taskId = "task-1",
        namespace = AndroidDownloadNamespace("server-1", "user-1", 1),
        bookId = "book-1",
        bookTitle = "The Sample Book",
        author = "Sample Author",
        coverUrl = "",
        resourceId = "resource-1",
        resourceTitle = "EPUB",
        format = "EPUB",
        readerType = "reflowable",
        assetId = "asset-1",
        sourceApiPath = "/api/books/book-1/resources/resource-1",
        sourceMimeType = "application/epub+zip",
        expectedBytes = 2048,
        transferredBytes = 2048,
        status = AndroidDownloadStatus.Completed,
        localReference = "/private/book-1.epub",
        verified = true,
        createdAtEpochMillis = 1,
        updatedAtEpochMillis = 2,
    )

    private fun string(resourceId: Int): String =
        InstrumentationRegistry.getInstrumentation().targetContext.getString(resourceId)
}
