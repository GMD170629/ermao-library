package com.ermao.library.features.workmanagement

import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.BookMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.BookDeletionOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.CoverMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult
import com.ermao.library.shared.modules.workmanagement.domain.ResourceMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import com.ermao.library.shared.modules.workmanagement.domain.ManagementTarget
import com.ermao.library.shared.modules.workmanagement.domain.ManagementSnapshot
import com.ermao.library.shared.modules.workmanagement.domain.ManagementFieldValue
import com.ermao.library.shared.modules.workmanagement.domain.RecognizedField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataApplyOutcome
import com.ermao.library.shared.modules.workmanagement.domain.ManagementAction
import com.ermao.library.shared.modules.workmanagement.domain.ManagementObject
import com.ermao.library.shared.modules.workmanagement.domain.ManagementField
import com.ermao.library.shared.modules.workmanagement.domain.ManagementSaveStage
import com.ermao.library.shared.modules.workmanagement.domain.ManagedBook
import com.ermao.library.shared.modules.workmanagement.domain.ManagedResource
import com.ermao.library.shared.modules.workmanagement.domain.ManagedAsset
import com.ermao.library.shared.modules.workmanagement.domain.ManagedDirectory
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementError
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
import com.ermao.library.shared.modules.workmanagement.domain.managementActions
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import com.ermao.library.shared.modules.workmanagement.createWorkManagementContext
import com.ermao.library.shared.modules.library.ContentRequestContext
import android.content.res.Configuration
import android.graphics.Bitmap
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import com.ermao.library.shared.modules.workmanagement.ManagementMenuContext
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.test.assertWidthIsEqualTo
import androidx.test.platform.app.InstrumentationRegistry
import android.view.KeyEvent
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.click
import androidx.compose.ui.test.swipeUp
import androidx.compose.ui.test.swipe
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.unit.dp
import com.ermao.library.ui.theme.WarmPageTheme
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import java.util.Locale
import java.io.File

class BookManagementCoverTest {
    @get:Rule val compose = createComposeRule()
    private val sharedContext = createWorkManagementContext("test", "Test", "https://library.example", "server", false, "user", 1)
    private val context = ContentRequestContext(sharedContext.profile, sharedContext.namespace)
    private val book = ManagedBook("book", "root", "Test book", "Author", "Description", "", null, emptyList(), "", false)
    private val snapshot = ManagementSnapshot(book, listOf(ManagedResource("resource-two", "book", "node-two", "Volume two", "", "EPUB", true,
        listOf(ManagementFieldValue(ManagementField.Title, "Volume two")), "", listOf(ManagedAsset("asset-two", "two.epub", "PRIMARY", "1 MB")))), null)
    private val targets = mutableListOf<ManagementTarget>()
    private var taps = 0
    private var preparationGate: kotlinx.coroutines.CompletableDeferred<Unit>? = null
    private var actionGate: kotlinx.coroutines.CompletableDeferred<Unit>? = null
    private var failAction = false
    private var actionCalls = 0
    private val repository = object : UnusedManagementRepository() {
        private suspend fun immediate(): WorkManagementResult<Unit> {
            actionCalls++
            actionGate?.await()
            return if (failAction) WorkManagementResult.Failure(WorkManagementError(WorkManagementErrorKind.Validation, "TEST_FAILED"))
                else WorkManagementResult.Content(Unit)
        }
        override suspend fun regenerateBookImage(context: BookManagementContext, bookId: String) = immediate()
        override suspend fun setBookReadingStatus(context: BookManagementContext, bookId: String, status: ManagedReadingStatus) = immediate()
        override suspend fun rescanBook(context: BookManagementContext, sourceNodeId: String) = immediate()
        override suspend fun deleteBook(context: BookManagementContext, bookId: String): WorkManagementResult<BookDeletionOutcome> {
            actionCalls++
            actionGate?.await()
            return WorkManagementResult.Content(BookDeletionOutcome(listOf(bookId)))
        }
        override suspend fun deleteResourceSource(context: BookManagementContext, bookId: String, resourceId: String, idempotencyKey: String) = immediate()

        override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot> {
            targets += target
            preparationGate?.await()
            return WorkManagementResult.Content(snapshot)
        }
    }

    private fun show(admin: Boolean = true, resource: Boolean = false, chinese: Boolean = false, longTitle: Boolean = false) {
        compose.setContent {
            val registryOwner = requireNotNull(androidx.activity.compose.LocalActivityResultRegistryOwner.current)
            val base = LocalContext.current
            val configuration = Configuration(LocalConfiguration.current).apply { setLocale(Locale.forLanguageTag(if (chinese) "zh-CN" else "en-US")) }
            val localizedContext = base.createConfigurationContext(configuration)
            // Pinned Compose 1.11 stringResource consumes LocalResources directly.
            // Overriding only LocalContext leaves popup labels in the device locale.
            CompositionLocalProvider(
                androidx.activity.compose.LocalActivityResultRegistryOwner provides registryOwner,
                LocalContext provides localizedContext,
                LocalConfiguration provides configuration,
                LocalResources provides localizedContext.resources,
            ) {
                WarmPageTheme(darkTheme = chinese) {
                    BookManagementHost(repository, context, admin, {}, {}, {}, {}, {}) {
                        LazyColumn {
                            items(20) { index ->
                                val target = if (resource) ManagementTarget(ManagementObject.Resource, "book", "resource-two", "Volume two")
                                    else ManagementTarget(ManagementObject.Book, "book", "book", if (longTitle) "A very long title ".repeat(30) else "Test book")
                                ManagementAnchor(target, Modifier.testTag("cover-$index"), menuContext = ManagementMenuContext(completed = false, kindleSendAvailable = resource)) {
                                    Box(Modifier.size(160.dp).clickable { taps++ }) { Text("Cover $index") }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    @Test fun bookDeletionUsesOneConfirmationWithoutTyping() = assertSingleDeletion(resource = false)
    @Test fun resourceDeletionUsesOneConfirmationWithoutTyping() = assertSingleDeletion(resource = true)

    private fun assertSingleDeletion(resource: Boolean) {
        preparationGate = kotlinx.coroutines.CompletableDeferred()
        actionGate = kotlinx.coroutines.CompletableDeferred()
        show(resource = resource)
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithTag("management-action-Delete").performClick()
        compose.onNodeWithTag("management-delete-confirmation").assertIsDisplayed()
        compose.onNodeWithTag("management-menu").assertDoesNotExist()
        compose.onAllNodes(hasSetTextAction()).assertCountEquals(0)
        compose.onNodeWithTag("management-delete-submit").assertIsNotEnabled()
        compose.runOnIdle { assertEquals(0, actionCalls) }
        compose.onNodeWithText("Cancel").performClick()
        compose.runOnIdle { preparationGate!!.complete(Unit) }
        compose.onNodeWithTag("management-delete-confirmation").assertDoesNotExist()
        compose.runOnIdle { assertEquals(0, actionCalls) }
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithTag("management-action-Delete").performClick()
        compose.onNodeWithTag("management-delete-confirmation").assertIsDisplayed()
        compose.onAllNodes(hasSetTextAction()).assertCountEquals(0)
        saveScreenshot(if (resource) "resource-delete-single" else "book-delete-single")
        compose.onNodeWithTag("management-delete-submit").performClick()
        compose.onNodeWithTag("management-delete-submit").assertIsNotEnabled()
        compose.runOnIdle { assertEquals(1, actionCalls); actionGate!!.complete(Unit) }
        compose.onNodeWithTag("management-delete-confirmation").assertDoesNotExist()
    }

    @Test fun immediateActionsStayInMenuWhilePreparingAndExecuting() {
        show()
        for (action in listOf(ManagementAction.Regenerate, ManagementAction.ReadingStatus, ManagementAction.Rescan)) {
            preparationGate = kotlinx.coroutines.CompletableDeferred()
            actionGate = kotlinx.coroutines.CompletableDeferred()
            compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
            compose.onNodeWithTag("management-action-${action.name}").performClick()
            compose.onNodeWithTag("management-menu").assertIsDisplayed()
            compose.onNodeWithText("Cancel").assertDoesNotExist()
            compose.onNodeWithTag("management-action-${action.name}").assertIsNotEnabled()
            compose.runOnIdle { preparationGate!!.complete(Unit) }
            compose.waitForIdle()
            compose.onNodeWithTag("management-menu").assertIsDisplayed()
            compose.onNodeWithText("Cancel").assertDoesNotExist()
            compose.onNodeWithTag("management-action-${action.name}").assertIsNotEnabled()
            saveScreenshot("inline-${action.name}")
            compose.runOnIdle { actionGate!!.complete(Unit) }
            compose.waitForIdle()
            compose.onNodeWithTag("management-menu").assertDoesNotExist()
        }
        compose.runOnIdle { assertEquals(3, actionCalls) }
    }

    @Test fun immediateFailureRetriesFromOriginalMenu() {
        failAction = true
        show()
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithTag("management-action-Regenerate").performClick()
        compose.onNodeWithTag("management-menu").assertIsDisplayed()
        compose.onNodeWithText("Cancel").assertDoesNotExist()
        compose.runOnIdle { assertEquals(1, actionCalls); failAction = false }
        compose.onNodeWithTag("management-action-Regenerate").performClick()
        compose.onNodeWithTag("management-menu").assertDoesNotExist()
        compose.runOnIdle { assertEquals(2, actionCalls) }
    }

    @Test fun tapAndScrollKeepTheirOwnersWhileLongPressOpensMenu() {
        show()
        compose.onNodeWithTag("cover-0").performTouchInput { click() }
        compose.runOnIdle { assertEquals(1, taps); assertTrue(targets.isEmpty()) }
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithText("Edit").assertIsDisplayed()
        compose.runOnIdle { assertEquals(1, taps); assertTrue(targets.isEmpty()) }
    }

    @Test fun menuUsesPressPointInsteadOfCoverBoundsAndReopensWithoutRequests() {
        show()
        // Stay away from Material's screen-edge clamping. A Popup owns a separate
        // window, so boundsInWindow cannot measure its movement across the screen.
        compose.onNodeWithTag("cover-0").performTouchInput { longClick(Offset(160f, 160f)) }
        val first = compose.onNodeWithTag("management-menu").fetchSemanticsNode().positionOnScreen
        // Existing Android platform menu geometry is 224dp (WarmPageComponentMetrics).
        compose.onNodeWithTag("management-menu").assertWidthIsEqualTo(224.dp)
        InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        compose.onNodeWithTag("cover-0").performTouchInput { longClick(Offset(220f, 220f)) }
        val second = compose.onNodeWithTag("management-menu").fetchSemanticsNode().positionOnScreen
        assertEquals(60f, second.x - first.x, 2f)
        assertEquals(60f, second.y - first.y, 2f)
        compose.runOnIdle { assertTrue(targets.isEmpty()); assertEquals(0, taps) }
    }

    @Test fun longTitleCannotExpandTheNativeMenu() {
        show(longTitle = true)
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithTag("management-menu").assertWidthIsEqualTo(224.dp)
        compose.onNodeWithText("Edit").assertIsDisplayed()
    }

    @Test fun scrollingDoesNotOpenManagementMenu() {
        show()
        compose.onNodeWithTag("cover-0").performTouchInput { swipeUp() }
        compose.runOnIdle { assertEquals(0, taps); assertTrue(targets.isEmpty()) }
        compose.onNodeWithText("Edit").assertDoesNotExist()
    }

    @Test fun resourceMenuTargetsThePressedResourceAndKeepsKindleForOrdinaryUsers() {
        show(admin = false, resource = true)
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithText("Send to Kindle").assertIsDisplayed()
        compose.onNodeWithText("Edit").assertDoesNotExist()
        compose.runOnIdle { assertTrue(targets.isEmpty()) }
    }

    @Test fun dirtyEditorRequiresDiscardConfirmation() {
        show()
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithText("Edit").performClick()
        compose.runOnIdle { assertEquals("book", targets.single().id) }
        compose.onNodeWithText("Title").performTextReplacement("Changed title")
        // Header cancellation keeps a dirty form until discard is confirmed.
        compose.onNodeWithText("Cancel").performClick()
        compose.onNodeWithText("Discard unsaved changes?").assertIsDisplayed()
        compose.onNodeWithText("Discard changes").performClick()
        compose.onNodeWithText("Changed title").assertDoesNotExist()
    }

    @Test fun chineseDarkMenuUsesLocalizedManagementActions() {
        show(chinese = true)
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithText("编辑").assertIsDisplayed()
        compose.onNodeWithText("重新生成图片").assertIsDisplayed()
        compose.onNodeWithText("识别").assertDoesNotExist()
    }

    @Test fun englishEditorHasNoCoverControls() = assertMetadataOnlyEditor(chinese = false)

    @Test fun chineseEditorHasNoCoverControls() = assertMetadataOnlyEditor(chinese = true)

    private fun assertMetadataOnlyEditor(chinese: Boolean) {
        show(chinese = chinese)
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithText(if (chinese) "识别" else "Recognize").assertDoesNotExist()
        saveScreenshot(if (chinese) "book-menu-zh" else "book-menu-en")
        compose.onNodeWithText(if (chinese) "编辑" else "Edit").performClick()
        compose.onNodeWithText(if (chinese) "标题" else "Title").assertIsDisplayed()
        listOf("Keep current cover", "Remove custom cover", "Choose from files", "Undo cover change",
            "保留当前封面", "移除独立封面", "从文件选择", "撤销封面修改").forEach {
            compose.onNodeWithText(it).assertDoesNotExist()
        }
        compose.onNodeWithText(if (chinese) "保存" else "Save").assertIsDisplayed()
        compose.onNodeWithText(if (chinese) "取消" else "Cancel").assertIsDisplayed()
        saveScreenshot(if (chinese) "book-editor-zh" else "book-editor-en")
        // Expand the native sheet before scrolling its form; scrolling content
        // alone does not move a partially expanded sheet to its expanded anchor.
        compose.onAllNodesWithText("Test book").onFirst().performTouchInput {
            swipe(start = center, end = Offset(center.x, -height * 12f))
        }
        compose.onNodeWithText(if (chinese) "保存" else "Save").assertIsDisplayed()
        compose.onNodeWithText(if (chinese) "取消" else "Cancel").assertIsDisplayed()
        saveScreenshot(if (chinese) "book-editor-bottom-zh" else "book-editor-bottom-en")
    }

    @Test fun resourceMenuRetainsIndependentCoverActionsWithoutRecognition() {
        show(resource = true)
        compose.onNodeWithTag("cover-0").performTouchInput { longClick() }
        compose.onNodeWithText("Recognize").assertDoesNotExist()
        compose.onNodeWithText("Upload cover").assertIsDisplayed()
        compose.onNodeWithText("Regenerate cover").assertIsDisplayed()
        saveScreenshot("resource-menu-en")
    }

    private fun saveScreenshot(name: String) {
        compose.waitForIdle()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val screenshot = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        val directory = File(requireNotNull(instrumentation.targetContext.getExternalFilesDir(null)), "detail-menu-qa")
        check(directory.isDirectory || directory.mkdirs())
        File(directory, "$name.png").outputStream().use { output ->
            check(screenshot.compress(Bitmap.CompressFormat.PNG, 100, output))
        }
        screenshot.recycle()
    }
}

private open class UnusedManagementRepository : WorkManagementRepository {
    override suspend fun loadBookCompleted(context: BookManagementContext, bookId: String): WorkManagementResult<Boolean> = error("Unexpected call: loadBookCompleted")
    override suspend fun saveBookFields(context: BookManagementContext, bookId: String, draft: BookMetadataDraft): WorkManagementResult<Unit> = error("Unexpected call: saveBookFields")
    override suspend fun replaceBookTags(context: BookManagementContext, bookId: String, current: List<String>, next: List<String>): WorkManagementResult<Unit> = error("Unexpected call: replaceBookTags")
    override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot> = error("Unexpected call: loadManagementSnapshot")
    override suspend fun saveResourceFields(context: BookManagementContext, bookId: String, resourceId: String, fields: List<ManagementFieldValue>): WorkManagementResult<Unit> = error("Unexpected call: saveResourceFields")
    override suspend fun saveSourcePresentation(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String): WorkManagementResult<Unit> = error("Unexpected call: saveSourcePresentation")
    override suspend fun regenerateBookImage(context: BookManagementContext, bookId: String): WorkManagementResult<Unit> = error("Unexpected call: regenerateBookImage")
    override suspend fun deleteResourceSource(context: BookManagementContext, bookId: String, resourceId: String, idempotencyKey: String): WorkManagementResult<Unit> = error("Unexpected call: deleteResourceSource")
    override suspend fun applyRecognizedFields(context: BookManagementContext, target: ManagementTarget, candidate: MetadataCandidate, fields: List<RecognizedField>): WorkManagementResult<MetadataApplyOutcome> = error("Unexpected call: applyRecognizedFields")
    override suspend fun applyDirectoryMetadata(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String): WorkManagementResult<Unit> = error("Unexpected call: applyDirectoryMetadata")

    override suspend fun uploadCover(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
        upload: CoverUpload,
    ): WorkManagementResult<CoverMutationOutcome> = error("Unexpected call: uploadCover")
    override suspend fun regenerateResourceCover(context: BookManagementContext, bookId: String, resourceId: String): WorkManagementResult<Unit> = error("Unexpected call: regenerateResourceCover")

    override suspend fun rescanBook(context: BookManagementContext, sourceNodeId: String): WorkManagementResult<Unit> = error("Unexpected call: rescanBook")
    override suspend fun deleteBook(context: BookManagementContext, bookId: String): WorkManagementResult<BookDeletionOutcome> = error("Unexpected call: deleteBook")

    override suspend fun loadMetadataProviders(context: BookManagementContext): WorkManagementResult<List<MetadataProvider>> = error("Unexpected call: loadMetadataProviders")
    override suspend fun searchMetadata(context: BookManagementContext, bookId: String, sourceNodeId: String, providerId: String, query: String): WorkManagementResult<MetadataSearchResult> = error("Unexpected call: searchMetadata")

    override suspend fun loadKindleSettings(context: BookManagementContext): WorkManagementResult<KindleSettings> = error("Unexpected call: loadKindleSettings")
    override suspend fun sendToKindle(context: BookManagementContext, bookId: String, assetId: String): WorkManagementResult<KindleSendOutcome> = error("Unexpected call: sendToKindle")
    override suspend fun setReadingStatus(context: BookManagementContext, resourceId: String, status: ManagedReadingStatus): WorkManagementResult<Unit> = error("Unexpected call: setReadingStatus")
    override suspend fun setBookReadingStatus(context: BookManagementContext, bookId: String, status: ManagedReadingStatus): WorkManagementResult<Unit> = error("Unexpected call: setBookReadingStatus")
}
