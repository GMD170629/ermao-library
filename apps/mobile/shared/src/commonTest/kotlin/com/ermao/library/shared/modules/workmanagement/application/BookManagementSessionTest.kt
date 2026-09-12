package com.ermao.library.shared.modules.workmanagement.application

import com.ermao.library.shared.core.feedback.OperationFeedbackKind
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

    @Test fun feedbackConsumptionCannotClearANewerOutcome() {
        val session = session(object : UnusedManagementRepository() {})
        session.reportRefreshFailure()
        val oldRevision = session.current.feedbackRevision
        assertEquals(OperationFeedbackKind.PartialSuccess, session.current.feedbackKind)
        session.reportRefreshFailure()
        val newRevision = session.current.feedbackRevision
        assertTrue(newRevision > oldRevision)
        session.clearFeedback(oldRevision)
        assertEquals("refreshFailed", session.current.notice)
        session.clearFeedback(newRevision)
        assertEquals(null, session.current.notice)
        session.close()
        assertEquals(null, session.current.notice)
    }

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
            assertEquals(5, session.menuItems.size)
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
        assertEquals(5, managementActions(ManagementObject.Book, true, false, false).size)
        val directory = managementActions(ManagementObject.Directory, true, false, false)
        assertFalse(directory.any { it.action == ManagementAction.Delete })
        assertFalse(directory.single { it.action == ManagementAction.Regenerate }.enabled)
        assertEquals(5, managementActions(ManagementObject.Resource, true, true, false).size)
        ManagementObject.entries.forEach { kind ->
            listOf(false, true).forEach { admin ->
                assertFalse(managementActions(kind, admin, true, true).any { it.action == ManagementAction.Recognize })
            }
        }
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
                calls += "tags:${next.joinToString()}"
                return if (calls.count { it.startsWith("tags:") } == 1) failure else WorkManagementResult.Content(Unit)
            }
        }
        val session = session(repo)
        session.open(target, ManagementMenuContext(completed = false)); session.select(ManagementAction.Edit)
        session.setField(ManagementField.Title, "New title")
        session.setField(ManagementField.Tags, "a,b\nsecond")
        session.save()
        assertEquals(listOf("metadata:New title", "tags:a,b, second"), calls)
        assertEquals(ManagementPhase.Editing, session.current.phase)
        assertEquals(ManagementSaveStage.Tags, session.current.saveStage)
        assertEquals("New title", session.current.draft.first { it.field == ManagementField.Title }.value)
        assertEquals("book", session.current.change?.bookId)
        assertEquals(null, session.current.notice)
        assertEquals(false, session.current.change?.coverChanged)
        session.save()
        assertEquals(listOf("metadata:New title", "tags:a,b, second", "metadata:New title", "tags:a,b, second"), calls)
        assertEquals(ManagementPhase.Closed, session.current.phase)
        assertEquals(false, session.current.change?.coverChanged)
    }

    @Test fun deleteConfirmationIsImmediateAndCancellationRejectsLatePreparation() = runBlocking {
        for (kind in listOf(ManagementObject.Book, ManagementObject.Resource)) {
            val gate = CompletableDeferred<Unit>()
            val repo = object : UnusedManagementRepository() {
                override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot> {
                    gate.await()
                    return WorkManagementResult.Content(snapshot)
                }
            }
            val session = session(repo)
            session.open(if (kind == ManagementObject.Book) target else ManagementTarget(kind, "book", "pressed", "pressed"))
            val job = launch(start = CoroutineStart.UNDISPATCHED) { session.select(ManagementAction.Delete) }
            assertEquals(ManagementPhase.DeleteConfirmation, session.current.phase)
            assertEquals(ManagementOperation.Loading, session.current.operation)
            session.confirmDelete() // No mutation while preparation is incomplete.
            session.close()
            gate.complete(Unit); job.join()
            assertEquals(ManagementPhase.Closed, session.current.phase)
            assertEquals(null, session.current.snapshot)
        }
    }

    @Test fun deletePreparationFailureRetriesWithinConfirmation() = runBlocking {
        var loads = 0
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) =
                if (++loads == 1) failure else WorkManagementResult.Content(snapshot)
        }
        val session = session(repo)
        session.open(target); session.select(ManagementAction.Delete)
        assertEquals(ManagementPhase.DeleteConfirmation, session.current.phase)
        assertEquals(null, session.current.snapshot)
        session.confirmDelete()
        session.retryPreparation()
        assertEquals(2, loads)
        assertEquals(ManagementPhase.DeleteConfirmation, session.current.phase)
        assertEquals(snapshot, session.current.snapshot)
        assertEquals(null, session.current.error)
    }

    @Test fun resourceDeletionNeedsOnlyConfirmationAndReusesKeyAfterNetworkFailure() = runBlocking {
        val keys = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun deleteResourceSource(context: BookManagementContext, bookId: String, resourceId: String, idempotencyKey: String): WorkManagementResult<Unit> {
                assertEquals("pressed", resourceId)
                keys += idempotencyKey
                return if (keys.size == 1) failure else WorkManagementResult.Content(Unit)
            }
        }
        val session = session(repo)
        session.open(ManagementTarget(ManagementObject.Resource, "book", "pressed", "stale title")); session.select(ManagementAction.Delete)
        assertTrue(keys.isEmpty())
        session.confirmDelete(); session.confirmDelete(); session.confirmDelete()
        assertEquals(listOf("operation-key", "operation-key"), keys)
        assertEquals("pressed", session.current.change?.resourceId)
        assertEquals(true, session.current.change?.deleted)
    }

    @Test fun failedImmediateRegenerationRetriesTheMutationWithoutReloadingTheSnapshot() = runBlocking {
        var snapshotCalls = 0
        var regenerationCalls = 0
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(
                context: BookManagementContext,
                target: ManagementTarget,
            ): WorkManagementResult<ManagementSnapshot> {
                snapshotCalls++
                return WorkManagementResult.Content(snapshot)
            }

            override suspend fun regenerateBookImage(
                context: BookManagementContext,
                bookId: String,
            ): WorkManagementResult<Unit> {
                regenerationCalls++
                return if (regenerationCalls == 1) failure else WorkManagementResult.Content(Unit)
            }
        }
        val session = session(repo)

        session.open(target)
        session.select(ManagementAction.Regenerate)

        assertEquals(1, snapshotCalls)
        assertEquals(1, regenerationCalls)
        assertEquals(ManagementPhase.Executing, session.current.phase)
        assertEquals("NETWORK_ERROR", session.current.error?.code)

        session.retryAction()

        assertEquals(1, snapshotCalls)
        assertEquals(2, regenerationCalls)
        assertEquals(ManagementPhase.Closed, session.current.phase)
        assertEquals("queued", session.current.notice)
        assertEquals(true, session.current.change?.coverChanged)
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
            override suspend fun saveSourcePresentation(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String): WorkManagementResult<Unit> {
                calls += "$sourceNodeId:$title"
                return if (calls.size == 1) failure else WorkManagementResult.Content(Unit)
            }
        }
        val session = session(repo)
        session.open(ManagementTarget(ManagementObject.Directory, "book", "directory", "Directory"))
        session.select(ManagementAction.Edit)
        assertEquals("Directory", session.current.draft.first { it.field == ManagementField.Title }.value)
        session.save()
        assertEquals(listOf("directory:Directory"), calls)
        assertEquals(ManagementPhase.Editing, session.current.phase)
        session.save()
        assertEquals(listOf("directory:Directory", "directory:Directory"), calls)
        assertEquals(false, session.current.change?.coverChanged)
    }

    @Test fun successfulBookSaveOrdersMetadataAndTagsWithoutChangingCover() = runBlocking {
        val calls = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun saveBookFields(context: BookManagementContext, bookId: String, draft: BookMetadataDraft): WorkManagementResult<Unit> { calls += "metadata"; return WorkManagementResult.Content(Unit) }
            override suspend fun replaceBookTags(context: BookManagementContext, bookId: String, current: List<String>, next: List<String>): WorkManagementResult<Unit> { calls += "tags"; return WorkManagementResult.Content(Unit) }
            override suspend fun saveSourcePresentation(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String): WorkManagementResult<Unit> { calls += sourceNodeId; return WorkManagementResult.Content(Unit) }
        }
        val session = session(repo)
        session.open(target, ManagementMenuContext(completed = false)); session.select(ManagementAction.Edit); session.save()
        assertEquals(listOf("metadata", "tags"), calls)
        assertEquals(ManagementPhase.Closed, session.current.phase)
        assertEquals(false, session.current.change?.coverChanged)
        val firstFeedbackRevision = session.current.feedbackRevision
        assertEquals(OperationFeedbackKind.Success, session.current.feedbackKind)
        assertEquals("saved", session.current.notice)
        session.open(target, ManagementMenuContext(completed = false)); session.select(ManagementAction.Edit); session.save()
        val secondFeedbackRevision = session.current.feedbackRevision
        assertTrue(secondFeedbackRevision > firstFeedbackRevision)
        session.clearFeedback(firstFeedbackRevision)
        assertEquals("saved", session.current.notice)
        session.clearFeedback(secondFeedbackRevision)
        session.close()
        session.open(target)
        assertEquals(null, session.current.notice)
    }

    @Test fun recognitionIsUnavailableWithoutAnyRepositoryCallsIncludingRetryAndReopening() = runBlocking {
        val repo = object : UnusedManagementRepository() {}
        for (admin in listOf(false, true)) for (kind in ManagementObject.entries) {
            val session = session(repo, admin)
            repeat(2) {
                session.open(ManagementTarget(kind, "book", if (kind == ManagementObject.Book) "book" else "pressed", "Title"))
                session.select(ManagementAction.Recognize)
                session.loadProviders()
                session.setQuery("Title")
                session.search()
                session.applyRecognition()
                session.retryPreparation()
                session.retryAction()
                assertEquals(ManagementPhase.Menu, session.current.phase)
                assertEquals(null, session.current.change)
                session.close()
                session.loadProviders()
                session.search()
                session.applyRecognition()
                assertEquals(ManagementPhase.Closed, session.current.phase)
            }
        }
    }

    @Test fun standaloneUploadRequiresCurrentUploadInteractionAndRetriesWithoutEnteringEditor() = runBlocking {
        val calls = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun uploadCover(context: BookManagementContext, bookId: String, resourceId: String, upload: CoverUpload): WorkManagementResult<CoverMutationOutcome> {
                calls += resourceId
                return if (calls.size == 1) failure else WorkManagementResult.Content(CoverMutationOutcome(resourceId, "/new-cover"))
            }
        }
        val session = session(repo)
        val resourceTarget = ManagementTarget(ManagementObject.Resource, "book", "pressed", "pressed")
        val upload = CoverUpload("cover.png", "image/png", byteArrayOf(1, 2, 3))
        session.open(resourceTarget)
        session.uploadResourceCover(upload, session.interactionId)
        session.select(ManagementAction.Edit)
        session.uploadResourceCover(upload, session.interactionId)
        assertTrue(calls.isEmpty())
        session.close()
        session.open(resourceTarget)
        session.select(ManagementAction.UploadCover)
        val oldInteraction = session.interactionId
        session.close()
        session.uploadResourceCover(upload, oldInteraction)
        session.open(resourceTarget.copy(id = "first"))
        session.select(ManagementAction.UploadCover)
        session.uploadResourceCover(upload, oldInteraction)
        assertTrue(calls.isEmpty())
        session.uploadResourceCover(upload, session.interactionId)
        assertEquals(ManagementPhase.CoverUpload, session.current.phase)
        session.uploadResourceCover(upload, session.interactionId)
        assertEquals(listOf("first", "first"), calls)
        assertEquals(true, session.current.change?.coverChanged)
        assertEquals(ManagementPhase.Closed, session.current.phase)
        session.uploadResourceCover(upload, session.interactionId)
        assertEquals(2, calls.size)
        val ordinary = session(repo, false)
        ordinary.open(resourceTarget)
        ordinary.select(ManagementAction.UploadCover)
        ordinary.uploadResourceCover(upload, ordinary.interactionId)
        assertEquals(2, calls.size)
    }

    @Test fun resourceEditorRetriesMetadataOnlyAndReopeningDiscardsCancelledDraft() = runBlocking {
        val titles = mutableListOf<String>()
        val repo = object : UnusedManagementRepository() {
            override suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget) = WorkManagementResult.Content(snapshot)
            override suspend fun saveResourceFields(context: BookManagementContext, bookId: String, resourceId: String, fields: List<ManagementFieldValue>): WorkManagementResult<Unit> {
                assertEquals("pressed", resourceId)
                assertFalse(fields.any { it.field == ManagementField.Cover })
                titles += fields.single { it.field == ManagementField.Title }.value
                return if (titles.size == 1) failure else WorkManagementResult.Content(Unit)
            }
        }
        val session = session(repo)
        val resourceTarget = ManagementTarget(ManagementObject.Resource, "book", "pressed", "pressed")
        session.open(resourceTarget)
        session.select(ManagementAction.Edit)
        assertFalse(session.isDirty)
        session.setField(ManagementField.Title, "Cancelled")
        assertTrue(session.isDirty)
        session.close()
        session.save()
        assertTrue(titles.isEmpty())
        session.open(resourceTarget)
        session.select(ManagementAction.Edit)
        assertFalse(session.isDirty)
        session.setField(ManagementField.Title, "Updated")
        session.save()
        assertEquals(ManagementPhase.Editing, session.current.phase)
        session.save()
        assertEquals(listOf("Updated", "Updated"), titles)
        assertEquals(false, session.current.change?.coverChanged)
        assertEquals(ManagementPhase.Closed, session.current.phase)
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
