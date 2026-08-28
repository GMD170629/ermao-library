package com.ermao.library.features.workmanagement

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.awaitLongPressOrCancellation
import androidx.compose.foundation.layout.absoluteOffset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import kotlin.math.roundToInt
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.isShiftPressed
import androidx.compose.ui.input.key.type
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import com.ermao.library.R
import com.ermao.library.features.workmanagement.infrastructure.AndroidCoverSelectionReader
import com.ermao.library.features.workmanagement.infrastructure.CoverSelectionResult
import com.ermao.library.shared.modules.workmanagement.BookManagementSession
import com.ermao.library.shared.modules.workmanagement.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.WorkManagementRepository
import com.ermao.library.shared.modules.workmanagement.ManagementAction
import com.ermao.library.shared.modules.workmanagement.ManagementObject
import com.ermao.library.shared.modules.workmanagement.ManagementTarget
import com.ermao.library.shared.modules.workmanagement.ManagementMenuContext
import com.ermao.library.shared.modules.workmanagement.ManagementPhase
import com.ermao.library.shared.modules.workmanagement.ManagementField
import com.ermao.library.shared.modules.workmanagement.ManagementSessionState
import com.ermao.library.shared.modules.workmanagement.ManagementChange
import com.ermao.library.shared.modules.workmanagement.CoverEdit
import com.ermao.library.shared.modules.workmanagement.WorkManagementErrorKind
import com.ermao.library.shared.modules.workmanagement.managementCandidateValue
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.theme.WarmPageThemeValues
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

class BookManagementController internal constructor(val session: BookManagementSession, private val scope: CoroutineScope) {
    internal var anchor: Any? by mutableStateOf(null)
    fun perform(operation: suspend BookManagementSession.() -> Unit) { scope.launch { session.operation() } }
    internal fun open(anchor: Any, target: ManagementTarget, menuContext: ManagementMenuContext) {
        if (session.current.operation != null) return
        this.anchor = anchor
        session.open(target, menuContext)
    }
}

private val LocalController = staticCompositionLocalOf<BookManagementController?> { null }
private val LocalDetailTarget = staticCompositionLocalOf<ManagementTarget?> { null }
private val LocalDetailMenuContext = staticCompositionLocalOf { ManagementMenuContext() }
private val LocalRevision = staticCompositionLocalOf { 0L }

@Composable
fun managementRevision(): Long = LocalRevision.current

@Composable
fun managementChange(): ManagementChange? = LocalController.current?.session?.state?.collectAsState()?.value?.change

@Composable
fun ManagementIdentityScope(target: ManagementTarget?, menuContext: ManagementMenuContext = ManagementMenuContext(), content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalDetailTarget provides target, LocalDetailMenuContext provides menuContext, content = content)
}

@Composable
fun ManageableBookCover(bookId: String, title: String, modifier: Modifier = Modifier, completed: Boolean? = null, content: @Composable () -> Unit) {
    ManagementAnchor(LocalDetailTarget.current ?: ManagementTarget(ManagementObject.Book, bookId, bookId, title), modifier,
        menuContext = if (LocalDetailTarget.current != null) LocalDetailMenuContext.current else ManagementMenuContext(completed = completed)) { content() }
}

/** Only consumes a successful long press; ordinary taps and parent scrolling keep their owners. */
@Composable
fun ManagementAnchor(
    target: ManagementTarget,
    modifier: Modifier = Modifier,
    menuContext: ManagementMenuContext = ManagementMenuContext(),
    menuExtras: (@Composable (close: () -> Unit) -> Unit)? = null,
    content: @Composable (open: () -> Unit) -> Unit,
) {
    val controller = LocalController.current
    val anchor = remember { Any() }
    var pressPosition by remember { mutableStateOf<Offset?>(null) }
    val haptic = LocalHapticFeedback.current
    val label = stringResource(R.string.management_open_actions, target.title)
    val state = controller?.session?.state?.collectAsState()?.value
    val cachedStates = controller?.session?.bookMenuStates?.collectAsState()?.value
    val resolvedContext = menuContext.copy(completed = menuContext.completed ?: cachedStates?.get(target.bookId))
    val latestContext by rememberUpdatedState(resolvedContext)
    val hasActions = com.ermao.library.shared.modules.workmanagement.managementMenuItems(target.kind, controller?.session?.canManageActions == true, menuContext.kindleSendAvailable, menuContext.hasRepresentativeResource).isNotEmpty() || menuExtras != null
    val revision = LocalRevision.current
    LaunchedEffect(controller, target.bookId, menuContext.completed, revision) {
        if (target.kind == ManagementObject.Book && menuContext.completed == null) controller?.session?.prepareBookMenu(target.bookId)
    }
    val open = { pressPosition = null; controller?.open(anchor, target, resolvedContext); Unit }
    val input = if (controller == null || !hasActions) Modifier else Modifier
        .pointerInput(target, controller) {
            awaitEachGesture {
                val down = awaitFirstDown(requireUnconsumed = false)
                val longPress = awaitLongPressOrCancellation(down.id)
                if (longPress != null) {
                    longPress.consume()
                    pressPosition = longPress.position
                    haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                    controller.open(anchor, target, latestContext)
                    do { val event = awaitPointerEvent(androidx.compose.ui.input.pointer.PointerEventPass.Initial); event.changes.forEach { it.consume() } } while (event.changes.any { it.pressed })
                }
            }
        }
        .onPreviewKeyEvent { event ->
            if (event.type == KeyEventType.KeyUp && (event.key == Key.Menu || (event.key == Key.F10 && event.isShiftPressed))) { open(); true } else false
        }
        .semantics { customActions = listOf(CustomAccessibilityAction(label) { open(); true }) }
    val density = LocalDensity.current
    val availableWidth = with(density) { LocalWindowInfo.current.containerSize.width.toDp() }
    val menuWidth = 280.dp.coerceAtMost((availableWidth - 32.dp).coerceAtLeast(0.dp))
    val menu: @Composable () -> Unit = {
        if (controller != null && controller.anchor === anchor && state != null) {
            DropdownMenu(
                expanded = state.phase == ManagementPhase.Menu && (controller.session.menuItems.isNotEmpty() || menuExtras != null),
                onDismissRequest = { if (controller.session.current.phase == ManagementPhase.Menu) controller.session.close() },
                modifier = Modifier.width(menuWidth).testTag("management-menu"),
            ) {
                menuExtras?.invoke(controller.session::close)
                Text(target.title, Modifier.padding(WarmPageThemeValues.spacing.two),
                    style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                controller.session.menuItems.forEach { item ->
                    DropdownMenuItem(text = { Text(actionLabel(item.action, state.copy(menuContext = resolvedContext)),
                        color = if (item.action == ManagementAction.Delete) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface) },
                        enabled = item.enabled,
                        onClick = { controller.perform { select(item.action) } })
                }
            }
        }
    }
    Box(modifier.then(input)) {
        content(open)
        val position = pressPosition
        if (position != null) {
            // A zero-sized layout anchor lets Material own placement/clamping at the press point.
            Box(Modifier.absoluteOffset { IntOffset(position.x.roundToInt(), position.y.roundToInt()) }.size(0.dp)) { menu() }
        } else { menu() }
    }
    DisposableEffect(controller, anchor) {
        onDispose { if (controller?.anchor === anchor && controller.session.current.phase == ManagementPhase.Menu) controller.session.close() }
    }
}

@Composable
fun BookManagementHost(
    repository: WorkManagementRepository,
    context: ContentRequestContext,
    canManage: Boolean,
    onUnauthorized: () -> Unit,
    onRefreshAuthorization: suspend () -> Unit,
    onChanged: suspend (ManagementChange) -> Unit,
    onOpenKindleSettings: () -> Unit,
    onOpenKindleQueue: () -> Unit,
    content: @Composable () -> Unit,
) {
    val appContext = LocalContext.current.applicationContext
    val scope = rememberCoroutineScope()
    val session = remember(repository, context, canManage) { BookManagementSession(repository,
        BookManagementContext(context.profile, context.namespace), canManage) { UUID.randomUUID().toString() } }
    val controller = remember(session, scope) { BookManagementController(session, scope) }
    val state by session.state.collectAsState()
    DisposableEffect(session) { onDispose(session::dispose) }
    var publishedRevision by remember(session) { mutableLongStateOf(0L) }
    LaunchedEffect(state.revision) {
        state.change?.let { change ->
            val snapshot = state.snapshot
            val paths = listOfNotNull(snapshot?.book?.coverUrl, snapshot?.directory?.coverUrl) + snapshot?.resources.orEmpty().map { it.coverUrl }
            paths.filter(String::isNotBlank).distinct().forEach { path ->
                try { com.ermao.library.platform.persistence.AndroidCoverCache.invalidate(appContext, context, path) }
                catch (_: com.ermao.library.platform.persistence.CoverCacheException) { session.reportRefreshFailure() }
            }
            onChanged(change)
            publishedRevision = state.revision
        }
    }
    LaunchedEffect(state.error) {
        when (state.error?.kind) {
            WorkManagementErrorKind.Unauthorized -> { session.close(); onUnauthorized() }
            WorkManagementErrorKind.Forbidden -> onRefreshAuthorization()
            else -> Unit
        }
    }
    CompositionLocalProvider(LocalController provides controller, LocalRevision provides publishedRevision) {
        Box {
            content()
            Box(Modifier.fillMaxSize(), contentAlignment = androidx.compose.ui.Alignment.BottomCenter) {
                ManagementPresentation(controller, state, onOpenKindleSettings, onOpenKindleQueue)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ManagementPresentation(controller: BookManagementController, state: ManagementSessionState, onSettings: () -> Unit, onQueue: () -> Unit) {
    val session = controller.session
    val context = LocalContext.current
    val reader = remember(context) { AndroidCoverSelectionReader(context.contentResolver) }
    var selectionFailed by remember(state.target) { mutableStateOf(false) }
    var pickerInteraction by remember { mutableLongStateOf(-1L) }
    var discard by remember { mutableStateOf(false) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null && pickerInteraction == session.interactionId) controller.perform {
            val expectedInteraction = pickerInteraction
            when (val result = reader.read(uri)) {
                is CoverSelectionResult.Ready -> if (expectedInteraction != interactionId) Unit else if (current.phase == ManagementPhase.CoverUpload) uploadResourceCover(result.upload) else setCover(CoverEdit.Replace, result.upload)
                else -> selectionFailed = true
            }
        }
    }
    val close = { if (state.operation == null || state.phase == ManagementPhase.Loading) { if (session.isDirty) discard = true else session.close() } }
    if (state.phase == ManagementPhase.DeleteConfirmation) {
        val target = state.target ?: return
        val resource = state.snapshot?.resources?.find { it.id == target.id }
        AlertDialog(onDismissRequest = { close() }, title = { Text(actionLabel(ManagementAction.Delete, state)) }, text = {
            Column(verticalArrangement = Arrangement.spacedBy(WarmPageThemeValues.spacing.two)) {
                Text(if (target.kind == ManagementObject.Book) stringResource(R.string.management_delete_book_warning, target.title)
                    else androidx.compose.ui.res.pluralStringResource(R.plurals.management_delete_resource_warning,
                        resource?.assets?.size ?: 0, target.title, resource?.assets?.size ?: 0))
                OutlinedTextField(state.confirmation, session::setConfirmation, label = { Text(target.title) }, enabled = state.operation == null)
                if (state.error != null) Text(stringResource(R.string.management_operation_failed), color = MaterialTheme.colorScheme.error)
            }
        }, confirmButton = { TextButton(onClick = { controller.perform { confirmDelete() } }, enabled = state.confirmation == target.title && state.operation == null) {
            Text(stringResource(R.string.management_delete), color = MaterialTheme.colorScheme.error)
        } }, dismissButton = { TextButton(onClick = { close() }, enabled = state.operation == null) { Text(stringResource(R.string.cancel_action)) } })
    }
    if (state.phase in listOf(ManagementPhase.Loading, ManagementPhase.LoadFailed, ManagementPhase.Executing, ManagementPhase.Result, ManagementPhase.Editing, ManagementPhase.Recognizing, ManagementPhase.Kindle, ManagementPhase.CoverUpload)) {
        ModalBottomSheet(onDismissRequest = { close() }) {
            Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(WarmPageThemeValues.spacing.two),
                verticalArrangement = Arrangement.spacedBy(WarmPageThemeValues.spacing.two)) {
                Text(state.target?.title.orEmpty(), style = MaterialTheme.typography.titleLarge)
                if (state.operation != null) CircularProgressIndicator()
                if (state.error != null) Text(stringResource(stageError(state)), color = MaterialTheme.colorScheme.error)
                when (state.phase) {
                    ManagementPhase.LoadFailed -> TextButton(onClick = { controller.perform { retryPreparation() } }) { Text(stringResource(R.string.retry_action)) }
                    ManagementPhase.Result -> {
                        state.metadataOutcome?.let { outcome ->
                            Text(stringResource(R.string.management_applied_fields))
                            outcome.appliedFields.forEach { wire ->
                                ManagementField.entries.find { it.wireName == wire.substringAfter('.') }?.let { Text(fieldLabel(it)) }
                            }
                            Text(stringResource(R.string.management_skipped_fields))
                            outcome.skippedFields.forEach { wire ->
                                ManagementField.entries.find { it.wireName == wire.substringAfter('.') }?.let { Text(fieldLabel(it)) }
                            }
                            Text(stringResource(when (outcome.coverStatus) {
                                "applied" -> R.string.management_result_cover_applied
                                "failed" -> R.string.management_result_cover_failed
                                else -> R.string.management_result_cover_not_selected
                            }))
                        }
                    }
                    ManagementPhase.Executing -> {
                        state.pendingAction?.let { Text(actionLabel(it, state)) }
                        if (state.error != null) TextButton(onClick = { controller.perform { retryAction() } }) { Text(stringResource(R.string.retry_action)) }
                    }
                    ManagementPhase.Editing -> {
                        state.draft.forEach { field -> OutlinedTextField(field.value, { session.setField(field.field, it) },
                            label = { Text(fieldLabel(field.field)) }, modifier = Modifier.fillMaxWidth(), enabled = state.operation == null,
                            minLines = if (field.field in listOf(ManagementField.Description, ManagementField.Tags)) 3 else 1) }
                        if (state.target?.kind != ManagementObject.Resource) {
                            if (state.target?.kind == ManagementObject.Book) Text(stringResource(R.string.management_tags_lines))
                            Text(stringResource(when (state.coverEdit) { CoverEdit.Keep -> R.string.management_cover_keep; CoverEdit.Replace -> R.string.management_cover_replace; CoverEdit.Remove -> R.string.management_cover_remove }))
                            state.coverUpload?.fileName?.let { Text(it) }
                            TextButton(onClick = { pickerInteraction = session.interactionId; picker.launch(arrayOf("image/jpeg", "image/png", "image/webp")) }, enabled = state.operation == null) { Text(stringResource(R.string.management_choose_cover_file)) }
                            TextButton(onClick = { session.setCover(CoverEdit.Remove, null) }, enabled = state.operation == null) { Text(stringResource(R.string.management_remove_cover)) }
                            if (state.coverEdit != CoverEdit.Keep) TextButton(onClick = { session.setCover(CoverEdit.Keep, null) }) { Text(stringResource(R.string.management_undo_cover)) }
                        }
                        Button(onClick = { controller.perform { save() } }, enabled = state.operation == null) { Text(stringResource(R.string.management_save)) }
                    }
                    ManagementPhase.CoverUpload -> {
                        Text(stringResource(R.string.management_cover_upload_hint))
                        Button(onClick = { pickerInteraction = session.interactionId; picker.launch(arrayOf("image/jpeg", "image/png", "image/webp")) }, enabled = state.operation == null) { Text(stringResource(R.string.management_choose_cover_file)) }
                    }
                    ManagementPhase.Recognizing -> {
                        state.providers.forEach { provider ->
                            Row { Checkbox(state.providerId == provider.id, { session.setProvider(provider.id) }, enabled = provider.enabled && state.operation == null); Text(provider.name) }
                        }
                        if (state.providers.none { it.enabled }) TextButton(onClick = { controller.perform { loadProviders() } }) { Text(stringResource(R.string.management_providers_retry)) }
                        OutlinedTextField(state.query, session::setQuery, label = { Text(stringResource(R.string.management_query)) }, modifier = Modifier.fillMaxWidth(), enabled = state.operation == null)
                        Button(onClick = { controller.perform { search() } }, enabled = state.operation == null && state.query.isNotBlank() && state.providerId.isNotBlank()) { Text(stringResource(R.string.management_search)) }
                        state.candidates.forEach { candidate ->
                            Row { Checkbox(candidate == state.selectedCandidate, { session.selectCandidate(candidate) }, enabled = state.operation == null); Text(candidate.title.orEmpty()) }
                        }
                        if (state.candidates.isEmpty()) Text(stringResource(R.string.management_no_candidates))
                        state.selectedCandidate?.let { candidate ->
                            if (state.target?.kind != ManagementObject.Directory) session.recognitionFields.forEach { field ->
                                Row { Checkbox(field in state.selectedFields, { session.setRecognizedField(field, it) }, enabled = state.operation == null)
                                    Column { Text(fieldLabel(field.field)); Text(stringResource(R.string.management_field_current, session.currentValue(field))); Text(stringResource(R.string.management_field_candidate, managementCandidateValue(candidate, field.field))) } }
                            } else Text(candidate.description.orEmpty())
                            Button(onClick = { controller.perform { applyRecognition() } }, enabled = state.operation == null && (state.target?.kind == ManagementObject.Directory || state.selectedFields.isNotEmpty())) { Text(stringResource(R.string.management_apply)) }
                        }
                    }
                    ManagementPhase.Kindle -> {
                        Text(state.kindleSettings?.recipientEmail.orEmpty())
                        if (state.kindleSettings?.ready != true) {
                            Text(stringResource(R.string.management_kindle_not_ready))
                            TextButton(onClick = { controller.perform { loadKindle() } }) { Text(stringResource(R.string.retry_action)) }
                        }
                        session.kindleOptions().forEach { resource -> resource.assets.filter { it.role == "PRIMARY" }.forEach { asset ->
                            Row { Checkbox(state.selectedAssetId == asset.id, { session.setAsset(asset.id) }, enabled = state.operation == null)
                                Text("${resource.title} · ${resource.format} · ${asset.size}") }
                        } }
                        TextButton(onClick = { session.close(); onSettings() }) { Text(stringResource(R.string.management_kindle_settings)) }
                        TextButton(onClick = { session.close(); onQueue() }) { Text(stringResource(R.string.management_kindle_queue)) }
                        Button(onClick = { controller.perform { sendKindle() } }, enabled = state.operation == null && state.kindleSettings?.ready == true && state.selectedAssetId.isNotBlank()) { Text(stringResource(R.string.management_send_kindle)) }
                    }
                    else -> Unit
                }
                if (selectionFailed) Text(stringResource(R.string.management_cover_read_failed), color = MaterialTheme.colorScheme.error)
                TextButton(onClick = { close() }, enabled = state.operation == null || state.phase == ManagementPhase.Loading) { Text(stringResource(R.string.cancel_action)) }
            }
        }
    }
    if (discard) AlertDialog(onDismissRequest = { discard = false }, title = { Text(stringResource(R.string.management_discard_title)) },
        confirmButton = { TextButton(onClick = { discard = false; session.close() }) { Text(stringResource(R.string.management_discard)) } },
        dismissButton = { TextButton(onClick = { discard = false }) { Text(stringResource(R.string.cancel_action)) } })
    state.notice?.let { notice ->
        // A single accessible success surface; no network response is treated as delivery completion.
        androidx.compose.material3.Snackbar(modifier = Modifier.padding(WarmPageThemeValues.spacing.two),
            action = { TextButton(onClick = session::clearFeedback) { Text(stringResource(R.string.close_action)) } }) {
            Text(stringResource(when (notice) { "queued" -> R.string.management_queued; "alreadyQueued" -> R.string.management_already_queued;
                "refreshFailed" -> R.string.management_refresh_failed; "deleted" -> R.string.management_deleted; "metadataPartial" -> R.string.management_metadata_partial; else -> R.string.management_saved }))
        }
    }
}

@Composable
private fun actionLabel(action: ManagementAction, state: ManagementSessionState): String = stringResource(when (action) {
    ManagementAction.Edit -> R.string.work_control_edit
    ManagementAction.Regenerate -> if (state.target?.kind == ManagementObject.Book) R.string.management_regenerate_book_image else R.string.work_control_regenerate_cover
    ManagementAction.ReadingStatus -> when (state.menuContext.completed) {
        true -> R.string.work_control_mark_unread
        false -> R.string.management_mark_finished
        null -> R.string.management_reading_status
    }
    ManagementAction.Recognize -> R.string.work_control_recognize
    ManagementAction.Rescan -> R.string.management_rescan
    ManagementAction.UploadCover -> R.string.management_upload_cover
    ManagementAction.Kindle -> R.string.work_control_send_kindle
    ManagementAction.Delete -> if (state.target?.kind == ManagementObject.Book) R.string.management_delete else R.string.management_delete_resource
})

@Composable
private fun fieldLabel(field: ManagementField): String = stringResource(when (field) {
    ManagementField.Title -> R.string.management_title
    ManagementField.Author -> R.string.management_author
    ManagementField.Description -> R.string.management_description
    ManagementField.SeriesName -> R.string.management_series
    ManagementField.SeriesIndex -> R.string.management_series_index
    ManagementField.Tags -> R.string.management_tags
    ManagementField.ResourceIndex -> R.string.management_resource_index
    ManagementField.Publisher -> R.string.management_publisher
    ManagementField.PublishedAt -> R.string.management_published_at
    ManagementField.Language -> R.string.management_language
    ManagementField.Isbn -> R.string.management_isbn
    ManagementField.Identifier -> R.string.management_identifier
    ManagementField.Narrator -> R.string.management_narrator
    ManagementField.Abridged -> R.string.management_abridged
    ManagementField.Cover -> R.string.management_cover
})

private fun stageError(state: ManagementSessionState): Int = when (state.saveStage?.name) {
    "Tags" -> R.string.management_tags_failed
    "Cover" -> R.string.management_cover_failed
    "Refresh" -> R.string.management_refresh_failed
    else -> R.string.management_operation_failed
}
