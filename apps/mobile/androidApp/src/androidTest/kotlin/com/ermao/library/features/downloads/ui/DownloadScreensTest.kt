package com.ermao.library.features.downloads.ui

import androidx.compose.runtime.mutableStateOf
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
                    onCancelDownload = {},
                    onRetryDownload = {},
                    onRemoveDownload = {},
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
                    onCancelDownload = {},
                    onRetryDownload = {},
                    onRemoveDownload = {},
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
                        completedBooks = listOf(book),
                        totalCompletedBytes = book.totalBytes,
                    ),
                    onBack = {},
                    onQueryChanged = {},
                    onClearQuery = {},
                    onOpenBook = { openedBook = it },
                    onRetry = {},
                    onCancelDownload = {},
                    onRetryDownload = {},
                    onRemoveDownload = {},
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
