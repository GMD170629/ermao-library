package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.LockReset
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ermao.library.ui.components.WarmSettingsEmptyState
import com.ermao.library.ui.components.WarmSettingsFilterBar
import com.ermao.library.ui.components.WarmSettingsFilterOption
import com.ermao.library.ui.components.WarmSettingsIcons
import com.ermao.library.ui.components.WarmSettingsIdentityHeader
import com.ermao.library.ui.components.WarmSettingsNavigationRow
import com.ermao.library.ui.components.rememberForwardProgress

private enum class QueueFilter { All, Running, Failed }

@Composable
fun KindleQueueScreen(
    state: AdministrativePageState<KindleQueueSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var filter by remember { mutableStateOf(QueueFilter.All) }
    var deleteTask by remember { mutableStateOf<KindleTask?>(null) }
    var selectedTask by remember { mutableStateOf<KindleTask?>(null) }
    AdministrativePage(
        title = AdministrativeCopy.KindleQueue,
        locale = locale,
        onBack = onBack,
        modifier = modifier,
        tabs = { QueueFilterRow(filter, { filter = it }, locale) },
    ) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            val tasks = snapshot.tasks.filter {
                when (filter) {
                    QueueFilter.All -> true
                    QueueFilter.Running -> it.status in setOf(QueueStatus.Queued, QueueStatus.Running)
                    QueueFilter.Failed -> it.status == QueueStatus.Failed
                }
            }
            if (tasks.isEmpty()) {
                WarmSettingsEmptyState(
                    title = AdministrativeCopy.Empty.text(locale),
                    message = when (filter) {
                        QueueFilter.All -> null
                        QueueFilter.Running -> AdministrativeCopy.Running.text(locale)
                        QueueFilter.Failed -> AdministrativeCopy.Failed.text(locale)
                    },
                )
            }
            tasks.forEach { task ->
                QueueTaskRow(
                    task,
                    locale,
                    onCancel = { onCommand(AdministrativeCommand.CancelKindleTask(task.id)) },
                    onRetry = { onCommand(AdministrativeCommand.RetryKindleTask(task.id)) },
                    onDelete = { deleteTask = task },
                    onMore = { selectedTask = task },
                )
            }
        }
    }
    deleteTask?.let { task ->
        AdministrativeConfirmDialog(
            AdministrativeCopy.DeleteTaskTitle, AdministrativeCopy.DeleteTaskBody, AdministrativeCopy.Delete,
            locale, onConfirm = { deleteTask = null; onCommand(AdministrativeCommand.DeleteKindleTask(task.id)) },
            onDismiss = { deleteTask = null },
        )
    }
    selectedTask?.let { task ->
        val actions = buildList {
            if (task.status in setOf(QueueStatus.Queued, QueueStatus.Running)) {
                add(AdministrativeSheetAction(AdministrativeCopy.CancelTask) { onCommand(AdministrativeCommand.CancelKindleTask(task.id)) })
            }
            if (task.status == QueueStatus.Failed) {
                add(AdministrativeSheetAction(AdministrativeCopy.RetryTask) { onCommand(AdministrativeCommand.RetryKindleTask(task.id)) })
            }
            if (task.status in setOf(QueueStatus.Completed, QueueStatus.Failed, QueueStatus.Cancelled)) {
                add(AdministrativeSheetAction(AdministrativeCopy.DeleteTask, destructive = true) { deleteTask = task })
            }
        }
        AdministrativeActionSheet(task.title, locale, actions, onDismiss = { selectedTask = null })
    }
}

@Composable
private fun QueueFilterRow(filter: QueueFilter, onSelect: (QueueFilter) -> Unit, locale: AdministrativeLocale) {
    WarmSettingsFilterBar(
        options = QueueFilter.entries.map { item ->
            WarmSettingsFilterOption(
                value = item,
                label = when (item) {
                    QueueFilter.All -> AdministrativeCopy.All
                    QueueFilter.Running -> AdministrativeCopy.Running
                    QueueFilter.Failed -> AdministrativeCopy.Failed
                }.text(locale),
            )
        },
        selected = filter,
        onSelect = onSelect,
        modifier = Modifier.testTag("administrative-kindle-queue-filters"),
    )
}

@Composable
private fun QueueTaskRow(
    task: KindleTask,
    locale: AdministrativeLocale,
    onCancel: () -> Unit,
    onRetry: () -> Unit,
    onDelete: () -> Unit,
    onMore: () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        WarmSettingsNavigationRow(
            title = task.title,
            summary = listOf(task.maskedRecipient, task.status.copy().text(locale)).joinToString(" · "),
            modifier = Modifier.testTag("administrative-kindle-task-${task.id}"),
            onClick = onMore,
        )
        task.progress?.let { progress ->
            val animatedProgress = rememberForwardProgress(progress, progressIdentity = task.id)
            LinearProgressIndicator(
                progress = { animatedProgress },
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            )
        }
        task.statusCode?.let {
            Text(
                it,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(horizontal = 16.dp),
            )
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            if (task.status in setOf(QueueStatus.Queued, QueueStatus.Running)) OutlinedButton(onClick = onCancel) {
                Icon(Icons.Outlined.Close, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(AdministrativeCopy.CancelTask.text(locale)) }
            if (task.status == QueueStatus.Failed) OutlinedButton(onClick = onRetry) {
                Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(AdministrativeCopy.RetryTask.text(locale)) }
            if (task.status in setOf(QueueStatus.Completed, QueueStatus.Failed, QueueStatus.Cancelled)) {
                OutlinedButton(onClick = onDelete) {
                    Icon(Icons.Outlined.Delete, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                    Text(AdministrativeCopy.Delete.text(locale), color = MaterialTheme.colorScheme.error) }
            }
        }
    }
    AdministrativeDivider()
}

internal fun QueueStatus.copy(): AdministrativeCopy = when (this) {
    QueueStatus.Queued -> AdministrativeCopy.Queued
    QueueStatus.Running -> AdministrativeCopy.Running
    QueueStatus.Completed -> AdministrativeCopy.Completed
    QueueStatus.Failed -> AdministrativeCopy.Failed
    QueueStatus.Cancelled -> AdministrativeCopy.Cancelled
    QueueStatus.Unknown -> AdministrativeCopy.Unknown
}

@Composable
private fun QueueStatus.color() = when (this) {
    QueueStatus.Failed -> MaterialTheme.colorScheme.error
    QueueStatus.Completed -> MaterialTheme.colorScheme.primary
    else -> MaterialTheme.colorScheme.onSurfaceVariant
}

@Composable
fun UsersScreen(
    state: AdministrativePageState<UsersSnapshot>,
    locale: AdministrativeLocale,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var search by remember { mutableStateOf("") }
    var enabledFilter by remember { mutableStateOf<Boolean?>(null) }
    AdministrativePage(
        AdministrativeCopy.UsersAndPermissions, locale, onBack, modifier,
        toolbarActions = {
            IconButton(onClick = { onNavigate(AdministrativeSettingsRoute.UserEdit()) }) {
                Icon(WarmSettingsIcons.Users, AdministrativeCopy.AddUser.text(locale))
            }
        },
        tabs = {
            WarmSettingsFilterBar(
                options = listOf(
                    WarmSettingsFilterOption(null, AdministrativeCopy.All.text(locale)),
                    WarmSettingsFilterOption(true, AdministrativeCopy.Enabled.text(locale)),
                    WarmSettingsFilterOption(false, AdministrativeCopy.Disabled.text(locale)),
                ),
                selected = enabledFilter,
                onSelect = { enabledFilter = it },
                modifier = Modifier.testTag("administrative-user-filters"),
            )
        },
    ) {
        AdministrativeTextField(search, { search = it }, AdministrativeCopy.Search, locale, textAlign = TextAlign.Start)
        PageStateContent(state, locale, onRetry) { snapshot ->
            val filteredUsers = snapshot.users.filter { user ->
                (search.isBlank() || user.displayName.contains(search, true) || user.email.contains(search, true)) &&
                    (enabledFilter == null || user.enabled == enabledFilter)
            }
            if (filteredUsers.isEmpty()) {
                WarmSettingsEmptyState(
                    title = AdministrativeCopy.Empty.text(locale),
                    message = AdministrativeCopy.Search.text(locale),
                )
            }
            filteredUsers.forEach { user ->
                AdministrativeNavigationRow(
                    title = user.displayName,
                    summary = listOf(
                        user.email,
                        user.role.copy().text(locale),
                        if (user.enabled) AdministrativeCopy.Enabled.text(locale) else AdministrativeCopy.Disabled.text(locale),
                    ).joinToString(" · "),
                    onClick = { onNavigate(AdministrativeSettingsRoute.UserEdit(user.id)) },
                    leading = WarmSettingsIcons.Users,
                    testTag = "administrative-user-${user.id}",
                )
            }
            if (snapshot.pageCount > 1) Text("${snapshot.page} / ${snapshot.pageCount} · ${snapshot.totalCount}", Modifier.padding(16.dp))
        }
    }
}

private fun UserRole.copy(): AdministrativeCopy = when (this) {
    UserRole.Administrator -> AdministrativeCopy.Administrator
    UserRole.Member -> AdministrativeCopy.Member
}

@Composable
fun UserEditScreen(
    state: AdministrativePageState<UserEditorSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    passwordResetRevision: Int = 0,
) {
    val snapshot = state.snapshot
    val initial = remember(snapshot) {
        UserDraft(snapshot?.user?.id, snapshot?.user?.displayName.orEmpty(), snapshot?.user?.email.orEmpty(),
            snapshot?.user?.role ?: UserRole.Member, snapshot?.user?.enabled ?: true, null,
            snapshot?.canManageSystem ?: false, snapshot?.canViewManualImports ?: false,
            snapshot?.selectedSourceIds.orEmpty(), snapshot?.user?.locale ?: AdministrativeLocale.ZhCn)
    }
    var draft by remember(initial) { mutableStateOf(initial) }
    var showReset by remember { mutableStateOf(false) }
    var showDelete by remember { mutableStateOf(false) }
    var showDiscard by remember { mutableStateOf(false) }
    val dirty = snapshot != null && draft != initial
    val busy = state.mutationInFlight
    val leave = { if (!busy) { if (dirty) showDiscard = true else onBack() } }
    androidx.activity.compose.BackHandler(enabled = dirty || busy) { leave() }
    androidx.compose.runtime.LaunchedEffect(passwordResetRevision) { showReset = false }
    AdministrativePage(
        title = if (draft.id == null) AdministrativeCopy.NewUser else AdministrativeCopy.EditUser,
        locale = locale, onBack = leave, modifier = modifier,
        toolbarActions = {
            AdministrativeSaveAction(AdministrativeCopy.SaveUser, locale,
                enabled = snapshot != null && !busy && dirty && draft.sharedDraft().isValid(draft.id == null),
                working = busy, onClick = { onCommand(AdministrativeCommand.SaveUser(draft)) })
        },
    ) {
        PageStateContent(state, locale, onRetry) { current ->
            AdministrativeSection(AdministrativeCopy.Users, locale)
            AdministrativeTextField(draft.displayName, { if (!busy) draft = draft.copy(displayName = it) }, AdministrativeCopy.UserName, locale, enabled = !busy)
            AdministrativeTextField(draft.email, { if (!busy) draft = draft.copy(email = it) }, AdministrativeCopy.Email, locale, enabled = !busy)
            if (draft.id == null) {
                AdministrativeTextField(draft.initialPassword.orEmpty(), { if (!busy) draft = draft.copy(initialPassword = it.ifEmpty { null }) },
                    AdministrativeCopy.InitialPassword, locale, password = true, supporting = AdministrativeCopy.InitialPasswordHint.text(locale), enabled = !busy)
            }
            EnumChoiceRow(AdministrativeCopy.InterfaceLanguage, AdministrativeLocale.entries, draft.locale,
                { if (!busy) draft = draft.copy(locale = it) }, locale, enabled = !busy) { if (it == AdministrativeLocale.ZhCn) "简体中文" else "English" }
            EnumChoiceRow(AdministrativeCopy.Role, UserRole.entries, draft.role,
                { if (!busy) draft = draft.copy(role = it) }, locale, enabled = !busy) { it.copy().text(locale) }
            if (draft.id != null) {
                EnumChoiceRow(AdministrativeCopy.AccountStatus, listOf(true, false), draft.enabled,
                    { if (!busy) draft = draft.copy(enabled = it) }, locale, enabled = !busy) {
                    (if (it) AdministrativeCopy.UserStatusActive else AdministrativeCopy.UserStatusDisabled).text(locale)
                }
                current.user?.createdAt?.let { created ->
                    val language = if (locale == AdministrativeLocale.ZhCn) java.util.Locale.SIMPLIFIED_CHINESE else java.util.Locale.US
                    val formatted = java.time.OffsetDateTime.parse(created).atZoneSameInstant(java.time.ZoneId.systemDefault())
                        .format(java.time.format.DateTimeFormatter.ofLocalizedDateTime(java.time.format.FormatStyle.MEDIUM).withLocale(language))
                    Text("${AdministrativeCopy.UserCreatedAt.text(locale)} $formatted", Modifier.padding(16.dp))
                }
            }
            if (draft.role == UserRole.Administrator) {
                Text(AdministrativeCopy.AdminPermissionsHint.text(locale), Modifier.padding(16.dp))
            } else {
                AdministrativeSection(AdministrativeCopy.ManagementPermissions, locale)
                AdministrativeSwitchRow(AdministrativeCopy.ManageSystemPermission.text(locale), draft.canManageSystem,
                    { draft = draft.copy(canManageSystem = it) }, supporting = AdministrativeCopy.ManageSystemPermissionDescription.text(locale), enabled = !busy)
                AdministrativeSection(AdministrativeCopy.LibraryPermissions, locale)
                Text(AdministrativeCopy.EmptyPermissionsHint.text(locale), Modifier.padding(16.dp))
                AdministrativeSwitchRow(AdministrativeCopy.ManualImports.text(locale), draft.canViewManualImports,
                    { draft = draft.copy(canViewManualImports = it) }, supporting = AdministrativeCopy.ManualImportsHint.text(locale), enabled = !busy)
                current.sources.forEach { source ->
                    AdministrativeSwitchRow(source.name, source.id in draft.sourceIds,
                        { checked -> draft = draft.copy(sourceIds = if (checked) draft.sourceIds + source.id else draft.sourceIds - source.id) },
                        supporting = source.path, enabled = !busy)
                }
            }
            if (current.user != null) {
                OutlinedButton(onClick = { showReset = true }, enabled = !busy, modifier = Modifier.padding(16.dp)) {
                    Icon(Icons.Outlined.LockReset, contentDescription = null)
                    Text(AdministrativeCopy.ResetPassword.text(locale))
                }
                DangerousAction(AdministrativeCopy.DeleteUser, locale, !busy) { showDelete = true }
            }
        }
    }
    if (showDiscard) AlertDialog(
        onDismissRequest = { showDiscard = false }, title = { Text(AdministrativeCopy.DiscardUserChanges.text(locale)) },
        confirmButton = { OutlinedButton(onClick = { showDiscard = false; onBack() }) { Text(AdministrativeCopy.DiscardChanges.text(locale)) } },
        dismissButton = { OutlinedButton(onClick = { showDiscard = false }) { Text(AdministrativeCopy.Cancel.text(locale)) } },
    )
    if (showReset) ResetPasswordDialog(draft.id.orEmpty(), locale, busy, state.failure, onCommand) { showReset = false }
    if (showDelete && snapshot?.user != null) UserDeletionDialog(snapshot.user, locale, busy, state.failure, onCommand) { showDelete = false }
}

@Composable
private fun ResetPasswordDialog(
    userId: String, locale: AdministrativeLocale, busy: Boolean, failure: AdministrativeFailure?,
    onCommand: (AdministrativeCommand) -> Unit, onDismiss: () -> Unit,
) {
    var password by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text(AdministrativeCopy.ResetPassword.text(locale)) },
        text = { Column {
            Text(AdministrativeCopy.ResetSessionsHint.text(locale))
            AdministrativeTextField(password, { if (!busy) password = it }, AdministrativeCopy.NewPassword, locale, password = true, enabled = !busy)
            if (failure != null) Text(failureText(failure, locale))
        } },
        confirmButton = { OutlinedButton(
            enabled = !busy && com.ermao.library.shared.modules.administrativesettings.isValidAdministrativePassword(password),
            onClick = { onCommand(AdministrativeCommand.ResetUserPassword(userId, password)) },
        ) { Text(AdministrativeCopy.ResetAndRequireLogin.text(locale)) } },
        dismissButton = { OutlinedButton(onClick = onDismiss, enabled = !busy) { Text(AdministrativeCopy.Cancel.text(locale)) } },
    )
}

@Composable
private fun UserDeletionDialog(
    user: AdministrativeUser, locale: AdministrativeLocale, busy: Boolean, failure: AdministrativeFailure?,
    onCommand: (AdministrativeCommand) -> Unit, onDismiss: () -> Unit,
) {
    var confirmation by remember(user.id) { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text(AdministrativeCopy.DeleteUserTitle.text(locale)) },
        text = { Column {
            Text(AdministrativeCopy.PermanentDeleteHint.text(locale))
            Text(user.email)
            AdministrativeTextField(confirmation, { if (!busy) confirmation = it }, AdministrativeCopy.DeleteEmailConfirmation, locale, enabled = !busy)
            if (failure != null) Text(failureText(failure, locale))
        } },
        confirmButton = { OutlinedButton(
            enabled = !busy && com.ermao.library.shared.modules.administrativesettings.isValidManagedUserDeletionConfirmation(user.email, confirmation),
            onClick = { onCommand(AdministrativeCommand.DeleteUser(user.id, confirmation)) },
        ) { Text(AdministrativeCopy.DeleteUser.text(locale)) } },
        dismissButton = { OutlinedButton(onClick = onDismiss, enabled = !busy) { Text(AdministrativeCopy.Cancel.text(locale)) } },
    )
}
