package com.ermao.library.shared.modules.workmanagement.application

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
import com.ermao.library.shared.modules.workmanagement.domain.ManagementMenuContext
import com.ermao.library.shared.modules.workmanagement.domain.ManagementSnapshot
import com.ermao.library.shared.modules.workmanagement.domain.ManagementFieldValue
import com.ermao.library.shared.modules.workmanagement.domain.RecognizedField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataApplyOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverEdit
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
import com.ermao.library.shared.modules.workmanagement.createWorkManagementContext
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.assertFalse

class BookManagementSessionTest {
    private val context = createWorkManagementContext("profile", "Library", "https://library.example", "server", false, "user", 1)
    private val book = ManagedBook("book", "book-node", "Book", "Author", "", "", null, listOf("old"), "/book-cover", false)
    private fun resource(id: String) = ManagedResource(id, "book", "node-$id", id, "", "EPUB", true,
        listOf(ManagementFieldValue(ManagementField.Title, id)), "/cover-$id", listOf(ManagedAsset("asset-$id", id, "PRIMARY", "1 MB")))
    private val snapshot = ManagementSnapshot(book, listOf(resource("first"), resource("pressed")), ManagedDirectory("directory", "Directory", "Description", "", null))
    private val target = ManagementTarget(ManagementObject.Book, "book", "book", "Book")
    private val failure = WorkManagementResult.Failure(WorkManagementError(WorkManagementErrorKind.Offline, "NETWORK_ERROR"))
    private fun session(repository: WorkManagementRepository, admin: Boolean = true) = BookManagementSession(repository, context, admin) { "operation-key" }

    @Test fun openingAndReopeningMenusNeverReadsManagementSnapshot() = runBlocking {
        var calls = 0
        val session = session(object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot> {
                calls++; return WorkManagementResult.Content(snapshot)
            }
        })
        repeat(3) {
            session.open(target, ManagementMenuContext(completed = false))
            assertEquals(ManagementPhase.Menu, session.current.phase)
            assertEquals(null, session.current.snapshot)
            assertEquals(6, session.menuItems.size)
            assertEquals(0, calls)
            session.close()
        }
        session.open(target, ManagementMenuContext(completed = false)); session.select(ManagementAction.Edit)
        assertEquals(1, calls)
        assertEquals(ManagementPhase.Editing, session.current.phase)
    }

    @Test fun pendingActionPreparationIsDeduplicatedAndRetryStaysOutsideMenu() = runBlocking {
        val pending = CompletableDeferred<Unit>()
        var calls = 0
        val session = session(object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot> {
                calls++; pending.await(); return if (calls == 1) failure else WorkManagementResult.Content(snapshot)
            }
        })
        session.open(target)
        val job = launch(start = CoroutineStart.UNDISPATCHED) { session.select(ManagementAction.Edit) }
        assertEquals(ManagementPhase.Loading, session.current.phase)
        session.select(ManagementAction.Delete)
        assertEquals(1, calls)
        pending.complete(Unit); job.join()
        assertEquals(ManagementPhase.LoadFailed, session.current.phase)
        session.retryPreparation()
        assertEquals(ManagementPhase.Editing, session.current.phase)
        assertEquals(2, calls)
    }

    @Test fun pagePreparationCoalescesReadsAndClearsCachedStateOnDispose() = runBlocking {
        val pending = CompletableDeferred<Unit>()
        var calls = 0
        val session = session(object : UnusedManagementRepository() {
            override suspend fun loadBookCompleted(context: BookManagementContext, bookId: String): WorkManagementResult<Boolean> {
                calls++; pending.await(); return WorkManagementResult.Content(true)
            }
        })
        val first = launch(start = CoroutineStart.UNDISPATCHED) { session.prepareBookMenu("book") }
        val second = launch(start = CoroutineStart.UNDISPATCHED) { session.prepareBookMenu("book") }
        assertEquals(1, calls)
        pending.complete(Unit); first.join(); second.join()
        session.prepareBookMenu("book")
        assertEquals(1, calls)
        session.open(target)
        assertEquals(true, session.current.menuContext.completed)
        assertTrue(session.menuItems.single { it.action == ManagementAction.ReadingStatus }.enabled)
        session.dispose()
        assertEquals(null, session.bookCompleted("book"))
    }

    @Test fun pagePreparationResponseCannotRepopulateADisposedSession() = runBlocking {
        val pending = CompletableDeferred<Unit>()
        val session = session(object : UnusedManagementRepository() {
            override suspend fun loadBookCompleted(context: BookManagementContext, bookId: String): WorkManagementResult<Boolean> {
                pending.await(); return WorkManagementResult.Content(true)
            }
        })
        val job = launch(start = CoroutineStart.UNDISPATCHED) { session.prepareBookMenu("book") }
        session.dispose(); pending.complete(Unit); job.join()
        assertEquals(null, session.bookCompleted("book"))
    }

    @Test fun unknownReadingStateDoesNotGuessAnUnreadBook() {
        val session = session(UnusedManagementRepository(), false)
        session.open(target)
        assertFalse(session.menuItems.single().enabled)
    }

    @Test fun closingDuringPreparationCannotUpdateTheNextTarget() = runBlocking {
        val pending = CompletableDeferred<Unit>()
        val session = session(object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot> {
                pending.await(); return WorkManagementResult.Content(snapshot)
            }
        })
        session.open(target)
        val job = launch(start = CoroutineStart.UNDISPATCHED) { session.select(ManagementAction.Edit) }
        session.close()
        session.open(ManagementTarget(ManagementObject.Resource, "book", "pressed", "Pressed"), ManagementMenuContext(kindleSendAvailable = true))
        pending.complete(Unit); job.join()
        assertEquals(ManagementPhase.Menu, session.current.phase)
        assertEquals("pressed", session.current.target?.id)
        assertEquals(null, session.current.snapshot)
    }

    @Test fun menuMatrixIncludesOnlyAuthorizedActions() {
        assertEquals(listOf(ManagementAction.ReadingStatus), managementActions(ManagementObject.Book, false, false, false).map { it.action })
        assertTrue(managementActions(ManagementObject.Directory, false, true, true).isEmpty())
        assertEquals(listOf(ManagementAction.Kindle), managementActions(ManagementObject.Resource, false, true, false).map { it.action })
        assertTrue(managementActions(ManagementObject.Resource, false, false, false).isEmpty())
        assertEquals(6, managementActions(ManagementObject.Book, true, false, false).size)
        val directory = managementActions(ManagementObject.Directory, true, false, false)
        assertFalse(directory.any { it.action == ManagementAction.Delete })
        assertFalse(directory.single { it.action == ManagementAction.Regenerate }.enabled)
        assertEquals(6, managementActions(ManagementObject.Resource, true, true, false).size)
    }

    @Test fun ordinaryUserCannotInvokeAdminActionsButCanChangeBookReadingStatus() = runBlocking {
        val calls = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun setBookReadingStatus(context: BookManagementContext, bookId: String, status: ManagedReadingStatus): WorkManagementResult<Unit> {
                calls += "$bookId:${status.name}"; return WorkManagementResult.Content(Unit)
            }
        }
        val session = session(repo, false)
        session.open(target, ManagementMenuContext(completed = false))
        session.select(ManagementAction.Edit)
        session.select(ManagementAction.Delete)
        assertEquals(ManagementPhase.Menu, session.current.phase)
        session.confirmDelete()
        assertTrue(calls.isEmpty())
        session.select(ManagementAction.ReadingStatus)
        assertEquals(listOf("book:Finished"), calls)
    }

    @Test fun bookSaveReportsPartialSuccessAndPreservesDraftForRetry() = runBlocking {
        val calls = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun saveBookFields(context: BookManagementContext, bookId: String, draft: BookMetadataDraft): WorkManagementResult<Unit> {
                calls += "metadata:${draft.title}"; return WorkManagementResult.Content(Unit)
            }
            override suspend fun replaceBookTags(context: BookManagementContext, bookId: String, current: List<String>, next: List<String>): WorkManagementResult<Unit> {
                calls += "tags:${next.joinToString()}"; return failure
            }
        }
        val session = session(repo)
        session.open(target, ManagementMenuContext(completed = false)); session.select(ManagementAction.Edit)
        session.setField(ManagementField.Title, "New title")
        session.setField(ManagementField.Tags, "a,b\nsecond")
        session.setCover(CoverEdit.Remove, null)
        session.save()
        assertEquals(listOf("metadata:New title", "tags:a,b, second"), calls)
        assertEquals(ManagementPhase.Editing, session.current.phase)
        assertEquals(ManagementSaveStage.Tags, session.current.saveStage)
        assertEquals("New title", session.current.draft.first { it.field == ManagementField.Title }.value)
        assertEquals("book", session.current.change?.bookId)
        assertEquals(null, session.current.notice)
    }

    @Test fun resourceDeletionRequiresExactTitleAndReusesKeyAfterNetworkFailure() = runBlocking {
        val keys = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun deleteResourceSource(context: BookManagementContext, bookId: String, resourceId: String, confirmation: String, idempotencyKey: String): WorkManagementResult<Unit> {
                assertEquals("pressed", resourceId); assertEquals("pressed", confirmation)
                keys += idempotencyKey
                return if (keys.size == 1) failure else WorkManagementResult.Content(Unit)
            }
        }
        val session = session(repo)
        session.open(ManagementTarget(ManagementObject.Resource, "book", "pressed", "stale title")); session.select(ManagementAction.Delete)
        session.setConfirmation("stale title"); session.confirmDelete()
        assertTrue(keys.isEmpty())
        session.setConfirmation("pressed"); session.confirmDelete(); session.confirmDelete()
        assertEquals(listOf("operation-key", "operation-key"), keys)
        assertEquals("pressed", session.current.change?.resourceId)
        assertEquals(true, session.current.change?.deleted)
    }

    @Test fun closingInteractionRejectsPendingSnapshotAndMutationResults() = runBlocking {
        val pending = CompletableDeferred<Unit>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot> {
                pending.await(); return WorkManagementResult.Content(snapshot)
            }
        }
        val session = session(repo)
        val job = launch(start = CoroutineStart.UNDISPATCHED) { session.open(target, ManagementMenuContext(completed = false)); session.select(ManagementAction.Edit) }
        session.close(); pending.complete(Unit); job.join()
        assertEquals(ManagementPhase.Closed, session.current.phase)
        assertEquals(null, session.current.snapshot)
    }

    @Test fun kindleUsesPressedAttachmentAndPreventsDuplicateSubmission() = runBlocking {
        val pending = CompletableDeferred<Unit>()
        val calls = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun loadKindleSettings(context: BookManagementContext) = WorkManagementResult.Content(KindleSettings("reader@kindle.com", true, "sender@example.com"))
            override suspend fun sendToKindle(context: BookManagementContext, bookId: String, assetId: String): WorkManagementResult<KindleSendOutcome> {
                calls += assetId; pending.await(); return WorkManagementResult.Content(KindleSendOutcome(true))
            }
        }
        val session = session(repo, false)
        session.open(ManagementTarget(ManagementObject.Resource, "book", "pressed", "Pressed"), ManagementMenuContext(kindleSendAvailable = true)); session.select(ManagementAction.Kindle)
        assertEquals("asset-pressed", session.current.selectedAssetId)
        assertEquals(2, session.kindleOptions().size)
        val job = launch(start = CoroutineStart.UNDISPATCHED) { session.sendKindle() }
        session.sendKindle()
        assertEquals(listOf("asset-pressed"), calls)
        pending.complete(Unit); job.join()
        assertEquals("alreadyQueued", session.current.notice)
    }
    @Test fun directoryKeepsItsIdentityEvenWhenItsCoverComesFromARepresentativeResource() = runBlocking {
        val calls = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) =
                WorkManagementResult.Content(snapshot.copy(directory = snapshot.directory?.copy(representativeResourceId = "pressed")))
            override suspend fun saveSourcePresentation(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String, removeCover: Boolean, upload: CoverUpload?): WorkManagementResult<Unit> {
                calls += "$sourceNodeId:$title:$removeCover"; return WorkManagementResult.Content(Unit)
            }
        }
        val session = session(repo)
        session.open(ManagementTarget(ManagementObject.Directory, "book", "directory", "Directory"))
        session.select(ManagementAction.Edit)
        assertEquals("Directory", session.current.draft.first { it.field == ManagementField.Title }.value)
        session.setCover(CoverEdit.Remove, null); session.save()
        assertEquals(listOf("directory:Directory:true"), calls)
    }

    @Test fun successfulBookSaveOrdersMetadataTagsAndIndependentCover() = runBlocking {
        val calls = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun saveBookFields(context: BookManagementContext, bookId: String, draft: BookMetadataDraft): WorkManagementResult<Unit> { calls += "metadata"; return WorkManagementResult.Content(Unit) }
            override suspend fun replaceBookTags(context: BookManagementContext, bookId: String, current: List<String>, next: List<String>): WorkManagementResult<Unit> { calls += "tags"; return WorkManagementResult.Content(Unit) }
            override suspend fun saveSourcePresentation(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String, removeCover: Boolean, upload: CoverUpload?): WorkManagementResult<Unit> { calls += sourceNodeId; return WorkManagementResult.Content(Unit) }
        }
        val session = session(repo)
        session.open(target, ManagementMenuContext(completed = false)); session.select(ManagementAction.Edit); session.setCover(CoverEdit.Remove, null); session.save()
        assertEquals(listOf("metadata", "tags", "book-node"), calls)
        assertEquals(ManagementPhase.Closed, session.current.phase)
        assertEquals(true, session.current.change?.coverChanged)
    }

    @Test fun recognitionKeepsAllResourceFieldsAndDefaultsToChangedNonemptyValues() = runBlocking {
        val candidate = MetadataCandidate("candidate", "provider", "pressed", "New author", null, emptyList(), null, null, null, null, null, null, 0.8,
            narrator = "Narrator", abridged = false, resourceIndex = 2.0)
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun loadMetadataProviders(context: BookManagementContext) = WorkManagementResult.Content(listOf(MetadataProvider("provider", "Provider", true)))
            override suspend fun searchMetadata(context: BookManagementContext, bookId: String, sourceNodeId: String, providerId: String, query: String): WorkManagementResult<MetadataSearchResult> {
                assertEquals("node-pressed", sourceNodeId); return WorkManagementResult.Content(MetadataSearchResult(listOf(candidate), null))
            }
            override suspend fun applyRecognizedFields(context: BookManagementContext, target: ManagementTarget, candidate: MetadataCandidate, fields: List<RecognizedField>) =
                WorkManagementResult.Content(MetadataApplyOutcome(listOf("book.author"), listOf("resource.narrator"), "failed"))
        }
        val session = session(repo)
        session.open(ManagementTarget(ManagementObject.Resource, "book", "pressed", "pressed")); session.select(ManagementAction.Recognize); session.search()
        assertEquals(setOf("book.author", "resource.narrator", "resource.abridged", "resource.resourceIndex"), session.current.selectedFields.map { it.wireValue }.toSet())
        session.applyRecognition()
        assertEquals(ManagementPhase.Result, session.current.phase)
        assertEquals("metadataPartial", session.current.notice)
        assertEquals(listOf("resource.narrator"), session.current.metadataOutcome?.skippedFields)
    }

}

private open class UnusedManagementRepository : WorkManagementRepository {
    override suspend fun loadBookCompleted(context: BookManagementContext, bookId: String): WorkManagementResult<Boolean> = error("Unexpected call: loadBookCompleted")
    override suspend fun saveBookFields(context: BookManagementContext, bookId: String, draft: BookMetadataDraft): WorkManagementResult<Unit> = error("Unexpected call: saveBookFields")
    override suspend fun replaceBookTags(context: BookManagementContext, bookId: String, current: List<String>, next: List<String>): WorkManagementResult<Unit> = error("Unexpected call: replaceBookTags")
    override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot> = error("Unexpected call: loadManagementSnapshot")
    override suspend fun saveResourceFields(context: BookManagementContext, bookId: String, resourceId: String, fields: List<ManagementFieldValue>): WorkManagementResult<Unit> = error("Unexpected call: saveResourceFields")
    override suspend fun saveSourcePresentation(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String, removeCover: Boolean, upload: CoverUpload?): WorkManagementResult<Unit> = error("Unexpected call: saveSourcePresentation")
    override suspend fun regenerateBookImage(context: BookManagementContext, bookId: String): WorkManagementResult<Unit> = error("Unexpected call: regenerateBookImage")
    override suspend fun deleteResourceSource(context: BookManagementContext, bookId: String, resourceId: String, confirmation: String, idempotencyKey: String): WorkManagementResult<Unit> = error("Unexpected call: deleteResourceSource")
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
