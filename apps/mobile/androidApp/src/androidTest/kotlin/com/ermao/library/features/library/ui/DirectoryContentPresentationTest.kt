package com.ermao.library.features.library.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.shared.createAndroidContentRepository
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.BookContentEntry
import com.ermao.library.shared.modules.library.BookDetailActionScope
import com.ermao.library.shared.modules.library.BookDetailObjectKind
import com.ermao.library.shared.modules.library.BookContentsPage
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

@RunWith(Parameterized::class)
class DirectoryContentPresentationTest(private val resourceCount: Int, private val isRoot: Boolean) {
    @get:Rule val composeRule = createComposeRule()

    @Test
    fun onlyBookRootRestoresIdentityAndActionsWhileChildDirectoryStaysCompact() {
        val androidContext = InstrumentationRegistry.getInstrumentation().targetContext
        val repository = createAndroidContentRepository(androidContext)
        val parsed = ServerBaseUrl.parse("https://directory-test.invalid")
        check(parsed is ServerBaseUrlParseResult.Valid)
        val context = ContentRequestContext(
            profile = ServerProfile("profile", "Test", parsed.baseUrl, "server", true, TlsMode.SystemTrust),
            namespace = PrivateDataNamespace("server", "user", 1),
        )
        val resources = (1..resourceCount).map { index ->
            ResourceContent(
                id = "resource-$index", title = "Resource $index", format = "EPUB", coverUrl = "",
                progressPercent = 25, readable = true, selected = false,
            )
        }
        val currentNode = entry("directory", null)
        val page = BookContentsPage(
            bookId = "book", currentSourceNodeId = currentNode.sourceNodeId,
            currentResourceId = null, currentNode = currentNode,
            currentResourceIds = resources.map { it.id }, parentSourceNodeId = null,
            breadcrumbs = emptyList(), entries = resources.map { entry("node-${it.id}", it.id) },
            page = 1, pageSize = 100, total = resourceCount, totalPages = 1,
        )
        var downloadsOpened = 0
        var shelvesOpened = 0
        var openedResource: String? = null
        var readingStatusScope: BookDetailActionScope? = null
        var downloadedResource: String? = null
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                WorkDetailScreen(
                    state = WorkDetailUiState(
                        isBookRoot = isRoot, isLoading = false, contents = page,
                        content = BookDetailContent(
                            book = BookCard("book", "Directory", "Author", "", 50),
                            seriesId = null, seriesName = null, authorFacetId = null,
                            description = "Book introduction",
                            tags = emptyList(), resources = resources, selectedResourceId = null,
                            continueResourceId = resources.lastOrNull()?.id,
                        ),
                    ),
                    repository = repository, context = context, onBack = {},
                    onSelectResource = { openedResource = it }, onOpenSourceNode = {},
                    onSelectContentsSort = {}, onSelectContentsPage = {}, onSelectReadingUnitsPage = {},
                    onRetrySurface = {}, onOpenShelfPicker = { shelvesOpened++ }, onDismissShelfPicker = {},
                    onToggleShelf = {}, onSaveShelves = {}, onShelfSaveFeedbackShown = {},
                    onViewShelves = {}, onOpenFacet = { _, _ -> }, onRetry = {},
                    onOpenMultiDownload = { downloadsOpened++ },
                    onOpenSelectedResource = { openedResource = it.id },
                    onSelectReadingStatus = { scope, _ -> readingStatusScope = scope },
                    onDownloadResource = { downloadedResource = it },
                )
            }
        }
        composeRule.onNodeWithText("50%").assertDoesNotExist()
        if (isRoot) {
            composeRule.onNodeWithTag("work-reader-action").assertIsDisplayed()
            if (resourceCount == 0) composeRule.onNodeWithTag("work-reader-action").assertIsNotEnabled()
            else {
                composeRule.onNodeWithTag("work-book-reading-resource").assertIsDisplayed()
                composeRule.onNodeWithTag("work-reader-action").performClick()
                composeRule.runOnIdle { assertEquals("resource-$resourceCount", openedResource) }
            }
            composeRule.onNodeWithTag("work-identity").assertIsDisplayed()
            composeRule.onNodeWithText("Author").assertIsDisplayed()
            composeRule.onNodeWithTag("work-directory-more").assertDoesNotExist()
            composeRule.onNodeWithTag("work-more-action").assertIsDisplayed()
            composeRule.onNodeWithTag("work-reading-status-action").assertIsDisplayed().performClick()
            composeRule.runOnIdle {
                assertEquals(BookDetailObjectKind.Book, readingStatusScope?.objectKind)
                assertEquals("book", readingStatusScope?.objectId)
            }
            composeRule.onNodeWithTag("work-shelf-action").assertIsDisplayed().performClick()
            composeRule.runOnIdle { assertEquals(1, shelvesOpened) }
            composeRule.onNodeWithTag("work-download-action").assertIsDisplayed().performClick()
            composeRule.runOnIdle { assertEquals(1, downloadsOpened) }
            composeRule.runOnIdle { assertEquals(null, downloadedResource) }
            composeRule.onNodeWithTag("work-detail-list").performScrollToNode(hasText("Book introduction"))
            composeRule.onNodeWithText("Book introduction").assertIsDisplayed()
            composeRule.onNodeWithTag("work-detail-list").performScrollToNode(hasTestTag("work-contents-breadcrumb-root"))
        } else {
            composeRule.onNodeWithTag("work-reader-action").assertDoesNotExist()
            composeRule.onNodeWithTag("work-book-reading-resource").assertDoesNotExist()
            composeRule.onNodeWithTag("work-identity").assertDoesNotExist()
            composeRule.onNodeWithText("Book introduction").assertDoesNotExist()
            composeRule.onNodeWithTag("work-download-action").assertDoesNotExist()
            composeRule.onNodeWithTag("work-shelf-action").assertDoesNotExist()
            composeRule.onNodeWithTag("work-reading-status-action").assertDoesNotExist()
        }
        composeRule.onNodeWithTag("work-contents-breadcrumb-root").assertIsDisplayed()
        if (resourceCount > 0) {
            if (isRoot) composeRule.onNodeWithTag("work-detail-list").performScrollToNode(hasTestTag("work-resource-resource-1"))
            composeRule.onNodeWithTag("work-resource-resource-1").assertIsDisplayed().performClick()
            composeRule.runOnIdle { assertEquals("resource-1", openedResource) }
        }
        composeRule.onNodeWithTag("work-directory-download").assertDoesNotExist()
        if (!isRoot) {
            composeRule.onNodeWithTag("work-directory-more").assertIsDisplayed().performClick()
            composeRule.onNodeWithTag("work-directory-shelf").assertDoesNotExist()
            composeRule.onNodeWithTag("work-book-edit").assertDoesNotExist()
            composeRule.onNodeWithTag("work-directory-download").assertIsDisplayed().performClick()
            composeRule.runOnIdle { assertEquals(1, downloadsOpened) }
            composeRule.onNodeWithTag("work-directory-download").assertDoesNotExist()
        }
    }

    @Test
    fun directoryMenuOnlyExposesItsOwnSubtreeDownload() {
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                DirectoryControlMenu(
                    onDownload = {},
                )
            }
        }
        composeRule.onNodeWithTag("work-directory-more").performClick()
        composeRule.onNodeWithTag("work-book-edit").assertDoesNotExist()
        composeRule.onNodeWithTag("work-directory-shelf").assertDoesNotExist()
        composeRule.onNodeWithTag("work-directory-download").assertIsDisplayed()
    }

    private fun entry(id: String, resourceId: String?) = BookContentEntry(
        sourceNodeId = id, parentSourceNodeId = null, name = id, title = id,
        description = null, kind = if (resourceId == null) "FOLDER" else "FILE",
        physicalKind = if (resourceId == null) "DIRECTORY" else "REGULAR_FILE",
        sizeBytes = null, observedAt = "2026-08-27T00:00:00Z", hasChildren = resourceId == null,
        resourceId = resourceId, representativeResourceId = null, coverUrl = null,
    )

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "resources={0}, root={1}")
        fun cases(): List<Array<Any>> = listOf(0, 1, 3).flatMap { count ->
            listOf(true, false).map { root -> arrayOf<Any>(count, root) }
        }
    }
}
