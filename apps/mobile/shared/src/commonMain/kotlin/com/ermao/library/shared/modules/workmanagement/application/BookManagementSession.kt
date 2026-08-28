package com.ermao.library.shared.modules.workmanagement.application

import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.CoverEdit
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.ManagementAction
import com.ermao.library.shared.modules.workmanagement.domain.ManagementChange
import com.ermao.library.shared.modules.workmanagement.domain.ManagementField
import com.ermao.library.shared.modules.workmanagement.domain.ManagementFieldValue
import com.ermao.library.shared.modules.workmanagement.domain.ManagementObject
import com.ermao.library.shared.modules.workmanagement.domain.ManagementSaveStage
import com.ermao.library.shared.modules.workmanagement.domain.ManagementSnapshot
import com.ermao.library.shared.modules.workmanagement.domain.ManagementTarget
import com.ermao.library.shared.modules.workmanagement.domain.ManagementMenuContext
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.RecognizedField
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementError
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import com.ermao.library.shared.modules.workmanagement.domain.editableManagementFields
import com.ermao.library.shared.modules.workmanagement.domain.managementActions
import com.ermao.library.shared.modules.workmanagement.domain.recognizedManagementFields
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class ManagementPhase { Closed, Loading, Menu, Editing, Recognizing, Kindle, DeleteConfirmation, CoverUpload, LoadFailed, Executing, Result }
enum class ManagementOperation { Loading, Saving, Searching, Applying, Executing }

data class ManagementSessionState(
    val phase: ManagementPhase = ManagementPhase.Closed,
    val operation: ManagementOperation? = null,
    val pendingAction: ManagementAction? = null,
    val target: ManagementTarget? = null,
    val snapshot: ManagementSnapshot? = null,
    val menuContext: ManagementMenuContext = ManagementMenuContext(),
    val draft: List<ManagementFieldValue> = emptyList(),
    val coverEdit: CoverEdit = CoverEdit.Keep,
    val coverUpload: CoverUpload? = null,
    val providers: List<MetadataProvider> = emptyList(),
    val providerId: String = "",
    val query: String = "",
    val candidates: List<MetadataCandidate> = emptyList(),
    val selectedCandidate: MetadataCandidate? = null,
    val selectedFields: List<RecognizedField> = emptyList(),
    val kindleSettings: KindleSettings? = null,
    val selectedAssetId: String = "",
    val confirmation: String = "",
    val error: WorkManagementError? = null,
    val saveStage: ManagementSaveStage? = null,
    val notice: String? = null,
    val metadataOutcome: com.ermao.library.shared.modules.workmanagement.domain.MetadataApplyOutcome? = null,
    val change: ManagementChange? = null,
    val revision: Long = 0,
)

/** Owns one native management interaction. UI dismissal/namespace replacement invalidates pending reads. */
class BookManagementSession(
    private val repository: WorkManagementRepository,
    private val context: BookManagementContext,
    private val canManage: Boolean,
    private val newOperationId: () -> String,
) {
    private val mutableState = MutableStateFlow(ManagementSessionState())
    val state: StateFlow<ManagementSessionState> = mutableState.asStateFlow()
    val current: ManagementSessionState get() = mutableState.value
    val canManageActions: Boolean get() = canManage
    private var generation = 0L
    private var deleteKey: String? = null
    val interactionId: Long get() = generation

    private val bookMenuCache = BookMenuStateCache(repository, context)
    val bookMenuStates = bookMenuCache.state
    suspend fun prepareBookMenu(bookId: String): Boolean? = bookMenuCache.prepare(bookId)
    fun bookCompleted(bookId: String): Boolean? = bookMenuStates.value[bookId]
    fun dispose() { close(); bookMenuCache.clear() }

    val menuItems get() = current.target?.let { target -> managementActions(target.kind, canManage,
        current.menuContext.kindleSendAvailable, current.menuContext.hasRepresentativeResource)
        .map { if (it.action == ManagementAction.ReadingStatus) it.copy(enabled =
            (current.menuContext.completed ?: bookCompleted(target.bookId)) != null) else it }
    }.orEmpty()
    val recognitionFields get() = current.target?.let { recognizedManagementFields(it.kind) }.orEmpty()
    val isDirty: Boolean get() = current.phase == ManagementPhase.Editing && current.snapshot?.let { snapshot -> current.target?.let { target ->
        current.draft != initialDraft(snapshot, target) || current.coverEdit != CoverEdit.Keep
    } } == true

    /** Opening a native menu is synchronous and never starts network work. */
    fun open(target: ManagementTarget, menuContext: ManagementMenuContext = ManagementMenuContext()) {
        generation++
        deleteKey = null
        mutableState.value = ManagementSessionState(phase = ManagementPhase.Menu,
            target = target, menuContext = menuContext.copy(completed = menuContext.completed ?: bookCompleted(target.bookId)),
            revision = current.revision, change = current.change)
    }

    suspend fun retryPreparation() {
        if (current.phase != ManagementPhase.LoadFailed) return
        current.pendingAction?.let { select(it) }
    }

    fun close() {
        generation++
        mutableState.value = ManagementSessionState(revision = current.revision, change = current.change)
    }

    fun reportRefreshFailure() {
        mutableState.value = current.copy(notice = "refreshFailed")
    }
    fun clearFeedback() { mutableState.value = current.copy(error = null, notice = null) }
    fun setField(field: ManagementField, value: String) {
        if (current.operation != null) return
        mutableState.value = current.copy(draft = current.draft.map { if (it.field == field) it.copy(value = value) else it }, error = null)
    }
    fun setCover(edit: CoverEdit, upload: CoverUpload?) {
        if (current.operation == null) mutableState.value = current.copy(coverEdit = edit, coverUpload = upload)
    }
    fun setQuery(value: String) { mutableState.value = current.copy(query = value) }
    fun setProvider(value: String) {
        if (current.operation == null && current.providers.any { it.id == value && it.enabled })
            mutableState.value = current.copy(providerId = value, candidates = emptyList(), selectedCandidate = null, selectedFields = emptyList())
    }
    fun setConfirmation(value: String) { mutableState.value = current.copy(confirmation = value) }
    fun setAsset(value: String) {
        if (kindleOptions().any { resource -> resource.assets.any { it.id == value && it.role == "PRIMARY" } })
            mutableState.value = current.copy(selectedAssetId = value)
    }
    fun kindleOptions() = current.snapshot?.resources.orEmpty().filter { it.kindleSendAvailable && it.format in listOf("EPUB", "PDF") }
    fun setRecognizedField(field: RecognizedField, selected: Boolean) {
        if (field !in recognitionFields || current.operation != null) return
        mutableState.value = current.copy(selectedFields = if (selected) (current.selectedFields + field).distinct() else current.selectedFields - field)
    }
    fun selectCandidate(candidate: MetadataCandidate) {
        if (candidate !in current.candidates || current.operation != null) return
        mutableState.value = current.copy(selectedCandidate = candidate, selectedFields = recognitionFields.filter { field ->
            candidateValue(candidate, field.field).let { it.isNotBlank() && !sameRecognizedValue(field.field, it, currentValue(field)) }
        })
    }
    fun currentValue(field: RecognizedField): String {
        val snapshot = current.snapshot ?: return ""
        val target = current.target ?: return ""
        if (field.field == ManagementField.Cover) return if (field.scope == ManagementObject.Book) snapshot.book.coverUrl
            else snapshot.resources.find { it.id == target.id }?.coverUrl.orEmpty()
        if (field.field == ManagementField.Abridged) return snapshot.resources.find { it.id == target.id }?.fields?.find { it.field == ManagementField.Abridged }?.value.orEmpty()
        return initialDraft(snapshot, if (field.scope == ManagementObject.Book) target.copy(kind = ManagementObject.Book, id = target.bookId) else target)
            .find { it.field == field.field }?.value.orEmpty()
    }

    suspend fun select(action: ManagementAction) {
        val before = current
        if (before.phase !in listOf(ManagementPhase.Menu, ManagementPhase.LoadFailed) ||
            before.operation != null || menuItems.none { it.action == action && it.enabled }) return
        val requestedTarget = before.target ?: return
        val token = generation
        // Capture the user's displayed reading-state intention before a server refresh.
        val intendedCompleted = before.menuContext.completed ?: bookCompleted(requestedTarget.bookId)
        mutableState.value = before.copy(phase = ManagementPhase.Loading, operation = ManagementOperation.Loading,
            pendingAction = action, error = null, notice = null, saveStage = null,
            menuContext = before.menuContext.copy(completed = intendedCompleted))
        val snapshot = when (val result = repository.loadManagementSnapshot(context, requestedTarget)) {
            is WorkManagementResult.Failure -> {
                if (token == generation) mutableState.value = current.copy(phase = ManagementPhase.LoadFailed, operation = null, error = result.error)
                return
            }
            is WorkManagementResult.Content -> result.value
        }
        if (token != generation) return
        val allowed = managementActions(requestedTarget.kind, canManage,
            snapshot.resources.find { it.id == requestedTarget.id }?.kindleSendAvailable == true,
            snapshot.directory?.representativeResourceId != null)
        if (allowed.none { it.action == action && it.enabled }) {
            mutableState.value = current.copy(phase = ManagementPhase.LoadFailed, operation = null,
                error = WorkManagementError(WorkManagementErrorKind.Forbidden, "MANAGEMENT_FORBIDDEN"))
            return
        }
        val title = when (requestedTarget.kind) {
            ManagementObject.Book -> snapshot.book.title
            ManagementObject.Directory -> snapshot.directory?.title
            ManagementObject.Resource -> snapshot.resources.find { it.id == requestedTarget.id }?.title
        } ?: requestedTarget.title
        val target = requestedTarget.copy(title = title)
        bookMenuCache.put(target.bookId, snapshot.book.completed)
        mutableState.value = current.copy(target = target, snapshot = snapshot, operation = null)
        when (action) {
            ManagementAction.Edit -> mutableState.value = current.copy(phase = ManagementPhase.Editing, draft = initialDraft(snapshot, target))
            ManagementAction.UploadCover -> mutableState.value = current.copy(phase = ManagementPhase.CoverUpload)
            ManagementAction.Delete -> { deleteKey = newOperationId(); mutableState.value = current.copy(phase = ManagementPhase.DeleteConfirmation, confirmation = "") }
            ManagementAction.Recognize -> {
                mutableState.value = current.copy(phase = ManagementPhase.Recognizing, query = target.title)
                loadProviders()
            }
            ManagementAction.Kindle -> {
                val options = kindleOptions()
                val preferred = options.find { it.id == target.id } ?: options.firstOrNull()
                mutableState.value = current.copy(phase = ManagementPhase.Kindle,
                    selectedAssetId = preferred?.assets?.firstOrNull { it.role == "PRIMARY" }?.id.orEmpty())
                loadKindle()
            }
            else -> { mutableState.value = current.copy(phase = ManagementPhase.Executing, pendingAction = action); executeImmediate(action) }
        }
    }

    suspend fun loadProviders() = runOperation(ManagementOperation.Loading) { token ->
        when (val result = repository.loadMetadataProviders(context)) {
            is WorkManagementResult.Failure -> fail(token, result)
            is WorkManagementResult.Content -> if (token == generation) mutableState.value = current.copy(
                providers = result.value, providerId = result.value.firstOrNull { it.enabled }?.id.orEmpty())
        }
    }
    suspend fun loadKindle() = runOperation(ManagementOperation.Loading) { token ->
        when (val result = repository.loadKindleSettings(context)) {
            is WorkManagementResult.Failure -> fail(token, result)
            is WorkManagementResult.Content -> if (token == generation) mutableState.value = current.copy(kindleSettings = result.value)
        }
    }
    suspend fun search() = runOperation(ManagementOperation.Searching) { token ->
        val target = current.target ?: return@runOperation
        if (current.providerId.isBlank() || current.query.isBlank()) return@runOperation
        when (val result = repository.searchMetadata(context, target.bookId, sourceNodeId(), current.providerId, current.query)) {
            is WorkManagementResult.Failure -> fail(token, result)
            is WorkManagementResult.Content -> if (token == generation) {
                mutableState.value = current.copy(candidates = result.value.candidates, selectedCandidate = null, selectedFields = emptyList())
                val candidate = result.value.candidates.firstOrNull()
                if (candidate != null) mutableState.value = current.copy(selectedCandidate = candidate,
                    selectedFields = recognitionFields.filter { candidateValue(candidate, it.field).let { value -> value.isNotBlank() && !sameRecognizedValue(it.field, value, currentValue(it)) } })
            }
        }
    }

    suspend fun save() = runOperation(ManagementOperation.Saving) { token ->
        if (current.phase != ManagementPhase.Editing) return@runOperation
        val target = current.target ?: return@runOperation
        val snapshot = current.snapshot ?: return@runOperation
        if (!canManage) { deny(token); return@runOperation }
        val fields = current.draft
        fun value(field: ManagementField) = fields.find { it.field == field }?.value.orEmpty().trim()
        if (value(ManagementField.Title).isBlank() || listOf(ManagementField.SeriesIndex, ManagementField.ResourceIndex).any {
            value(it).isNotBlank() && value(it).toDoubleOrNull()?.isFinite() != true
        }) { invalid(token, "MANAGEMENT_FIELDS_INVALID"); return@runOperation }
        val upload = current.coverUpload
        val coverEdit = current.coverEdit
        if (coverEdit == CoverEdit.Replace && upload == null) { invalid(token, "COVER_MISSING"); return@runOperation }
        mutableState.value = current.copy(saveStage = ManagementSaveStage.Metadata)
        val result = when (target.kind) {
            ManagementObject.Book -> repository.saveBookFields(context, target.bookId, BookMetadataDraft(
                value(ManagementField.Title), value(ManagementField.Author), value(ManagementField.Description),
                value(ManagementField.SeriesName).ifBlank { null }, value(ManagementField.SeriesIndex).toDoubleOrNull()))
            ManagementObject.Directory -> repository.saveSourcePresentation(context, target.bookId, target.id,
                value(ManagementField.Title), value(ManagementField.Description), coverEdit == CoverEdit.Remove, upload)
            ManagementObject.Resource -> repository.saveResourceFields(context, target.bookId, target.id, fields)
        }
        if (!succeeded(token, result)) return@runOperation
        if (target.kind == ManagementObject.Book) {
            mutableState.value = current.copy(saveStage = ManagementSaveStage.Tags)
            val tags = value(ManagementField.Tags).split('\n').map(String::trim).filter(String::isNotEmpty).distinct()
            if (!succeeded(token, repository.replaceBookTags(context, target.bookId, snapshot.book.tags, tags))) { if (token == generation) changed(target, false); return@runOperation }
            if (coverEdit != CoverEdit.Keep) {
                mutableState.value = current.copy(saveStage = ManagementSaveStage.Cover)
                if (!succeeded(token, repository.saveSourcePresentation(context, target.bookId, snapshot.book.sourceNodeId,
                    value(ManagementField.Title), value(ManagementField.Description), coverEdit == CoverEdit.Remove, upload))) { if (token == generation) changed(target, false); return@runOperation }
            }
        }
        complete(token, target, "saved", coverChanged = coverEdit != CoverEdit.Keep)
    }

    suspend fun uploadResourceCover(upload: CoverUpload) = runOperation(ManagementOperation.Saving) { token ->
        val target = current.target ?: return@runOperation
        if (!canManage || target.kind != ManagementObject.Resource) { deny(token); return@runOperation }
        if (succeeded(token, repository.uploadCover(context, target.bookId, target.id, upload))) complete(token, target, "saved", coverChanged = true)
    }

    suspend fun applyRecognition() = runOperation(ManagementOperation.Applying) { token ->
        val target = current.target ?: return@runOperation
        val candidate = current.selectedCandidate ?: return@runOperation
        if (!canManage) { deny(token); return@runOperation }
        if (target.kind == ManagementObject.Directory) {
            if (succeeded(token, repository.applyDirectoryMetadata(context, target.bookId, target.id,
                candidate.title?.trim()?.ifBlank { null } ?: target.title,
                candidate.description?.trim()?.ifBlank { null } ?: current.snapshot?.directory?.description.orEmpty()))) complete(token, target, "saved")
        } else {
            if (current.selectedFields.isEmpty()) return@runOperation
            when (val result = repository.applyRecognizedFields(context, target, candidate, current.selectedFields)) {
                is WorkManagementResult.Failure -> fail(token, result)
                is WorkManagementResult.Content -> if (token == generation) {
                    mutableState.value = current.copy(metadataOutcome = result.value)
                    complete(token, target,
                        if (result.value.coverStatus == "failed" || result.value.skippedFields.isNotEmpty()) "metadataPartial" else "saved",
                        coverChanged = result.value.coverStatus == "applied")
                    mutableState.value = current.copy(phase = ManagementPhase.Result)
                }
            }
        }
    }

    suspend fun sendKindle() = runOperation(ManagementOperation.Executing) { token ->
        val target = current.target ?: return@runOperation
        val asset = current.selectedAssetId
        if (current.kindleSettings?.ready != true || kindleOptions().none { resource -> resource.assets.any { it.id == asset && it.role == "PRIMARY" } }) {
            invalid(token, "KINDLE_NOT_READY"); return@runOperation
        }
        when (val result = repository.sendToKindle(context, target.bookId, asset)) {
            is WorkManagementResult.Failure -> fail(token, result)
            is WorkManagementResult.Content -> if (token == generation) mutableState.value = current.copy(phase = ManagementPhase.Closed,
                notice = if (result.value.alreadyQueued) "alreadyQueued" else "queued")
        }
    }

    suspend fun confirmDelete() = runOperation(ManagementOperation.Executing) { token ->
        if (current.phase != ManagementPhase.DeleteConfirmation) return@runOperation
        val target = current.target ?: return@runOperation
        if (!canManage) { deny(token); return@runOperation }
        if (current.confirmation != target.title) { invalid(token, "CONFIRMATION_MISMATCH"); return@runOperation }
        val result = when (target.kind) {
            ManagementObject.Book -> repository.deleteBook(context, target.bookId)
            ManagementObject.Resource -> repository.deleteResourceSource(context, target.bookId, target.id, current.confirmation, requireNotNull(deleteKey))
            ManagementObject.Directory -> { deny(token); return@runOperation }
        }
        if (succeeded(token, result)) complete(token, target, "deleted", deleted = true)
    }

    suspend fun retryAction() { current.pendingAction?.let { select(it) } }

    private suspend fun executeImmediate(action: ManagementAction) = runOperation(ManagementOperation.Executing) { token ->
        val target = current.target ?: return@runOperation
        val snapshot = current.snapshot ?: return@runOperation
        val result = when (action) {
            ManagementAction.ReadingStatus -> repository.setBookReadingStatus(context, target.bookId,
                if (current.menuContext.completed == true) ManagedReadingStatus.Unread else ManagedReadingStatus.Finished)
            ManagementAction.Regenerate -> when (target.kind) {
                ManagementObject.Book -> repository.regenerateBookImage(context, target.bookId)
                ManagementObject.Resource -> repository.regenerateResourceCover(context, target.bookId, target.id)
                ManagementObject.Directory -> snapshot.directory?.representativeResourceId?.let {
                    repository.regenerateResourceCover(context, target.bookId, it)
                } ?: return@runOperation
            }
            ManagementAction.Rescan -> repository.rescanBook(context, sourceNodeId())
            else -> return@runOperation
        }
        if (succeeded(token, result)) complete(token, target,
            if (action == ManagementAction.Rescan || (action == ManagementAction.Regenerate && target.kind == ManagementObject.Book)) "queued" else "saved",
            coverChanged = action == ManagementAction.Regenerate, readingStatusChanged = action == ManagementAction.ReadingStatus)
    }

    private fun sourceNodeId(): String {
        val target = requireNotNull(current.target)
        val snapshot = requireNotNull(current.snapshot)
        return when (target.kind) {
            ManagementObject.Book -> snapshot.book.sourceNodeId
            ManagementObject.Directory -> target.id
            ManagementObject.Resource -> requireNotNull(snapshot.resources.find { it.id == target.id }).sourceNodeId
        }
    }
    private suspend fun runOperation(operation: ManagementOperation, block: suspend (Long) -> Unit) {
        if (current.operation != null) return
        val token = generation
        mutableState.value = current.copy(operation = operation, error = null, notice = null)
        try { block(token) } finally { if (token == generation) mutableState.value = current.copy(operation = null) }
    }
    private fun succeeded(token: Long, result: WorkManagementResult<*>): Boolean {
        if (token != generation) return false
        if (result is WorkManagementResult.Failure) { fail(token, result); return false }
        return true
    }
    private fun fail(token: Long, result: WorkManagementResult.Failure) {
        if (token == generation) mutableState.value = current.copy(error = result.error)
    }
    private fun deny(token: Long) = fail(token, WorkManagementResult.Failure(WorkManagementError(WorkManagementErrorKind.Forbidden, "MANAGEMENT_FORBIDDEN")))
    private fun invalid(token: Long, code: String) = fail(token, WorkManagementResult.Failure(WorkManagementError(WorkManagementErrorKind.Validation, code)))
    private fun changed(target: ManagementTarget, coverChanged: Boolean, deleted: Boolean = false, readingStatusChanged: Boolean = false) {
        mutableState.value = current.copy(revision = current.revision + 1,
            change = ManagementChange(target.bookId, target.id.takeIf { target.kind == ManagementObject.Resource }, deleted, coverChanged, readingStatusChanged))
    }
    private fun complete(token: Long, target: ManagementTarget, notice: String, coverChanged: Boolean = false, deleted: Boolean = false, readingStatusChanged: Boolean = false) {
        if (token != generation) return
        bookMenuCache.invalidate(target.bookId)
        if (readingStatusChanged) bookMenuCache.put(target.bookId, current.menuContext.completed != true)
        changed(target, coverChanged, deleted, readingStatusChanged)
        mutableState.value = current.copy(phase = ManagementPhase.Closed, notice = notice, saveStage = null, coverUpload = null)
    }
}

private fun initialDraft(snapshot: ManagementSnapshot, target: ManagementTarget): List<ManagementFieldValue> =
    editableManagementFields(target.kind).map { field -> ManagementFieldValue(field, when (target.kind) {
        ManagementObject.Book -> when (field) {
            ManagementField.Title -> snapshot.book.title
            ManagementField.Author -> snapshot.book.author
            ManagementField.Description -> snapshot.book.description
            ManagementField.SeriesName -> snapshot.book.seriesName
            ManagementField.SeriesIndex -> snapshot.book.seriesIndex?.toString().orEmpty()
            ManagementField.Tags -> snapshot.book.tags.joinToString("\n")
            else -> ""
        }
        ManagementObject.Directory -> if (field == ManagementField.Title) snapshot.directory?.title.orEmpty() else snapshot.directory?.description.orEmpty()
        ManagementObject.Resource -> snapshot.resources.find { it.id == target.id }?.fields?.find { it.field == field }?.value.orEmpty()
    }) }

fun candidateValue(candidate: MetadataCandidate, field: ManagementField): String = when (field) {
    ManagementField.Title -> candidate.title
    ManagementField.Author -> candidate.author
    ManagementField.Description -> candidate.description
    ManagementField.SeriesName -> candidate.seriesName
    ManagementField.SeriesIndex -> candidate.seriesIndex?.toString()
    ManagementField.Tags -> candidate.tags.joinToString("\n")
    ManagementField.Publisher -> candidate.publisher
    ManagementField.PublishedAt -> candidate.publishedAt
    ManagementField.Language -> candidate.language
    ManagementField.Isbn -> candidate.isbn
    ManagementField.Identifier -> candidate.identifier
    ManagementField.Narrator -> candidate.narrator
    ManagementField.Abridged -> candidate.abridged?.toString()
    ManagementField.ResourceIndex -> candidate.resourceIndex?.toString()
    ManagementField.Cover -> candidate.coverUrl
}.orEmpty()

private fun sameRecognizedValue(field: ManagementField, candidate: String, current: String): Boolean = when (field) {
    ManagementField.SeriesIndex, ManagementField.ResourceIndex -> candidate.toDoubleOrNull() == current.toDoubleOrNull()
    ManagementField.Tags -> candidate.lines().map(String::trim).toSet() == current.lines().map(String::trim).toSet()
    else -> candidate.trim() == current.trim()
}
