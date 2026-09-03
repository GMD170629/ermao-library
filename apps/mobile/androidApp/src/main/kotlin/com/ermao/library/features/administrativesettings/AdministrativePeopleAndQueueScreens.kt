package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.outlined.PersonAdd
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ermao.library.ui.components.SettingsTextField
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
    AdministrativePage(AdministrativeCopy.KindleQueue, locale, onBack, modifier) {
        QueueFilterRow(filter, { filter = it }, locale)
        PageStateContent(state, locale, onRetry) { snapshot ->
            val tasks = snapshot.tasks.filter {
                when (filter) {
                    QueueFilter.All -> true
                    QueueFilter.Running -> it.status in setOf(QueueStatus.Queued, QueueStatus.Running)
                    QueueFilter.Failed -> it.status == QueueStatus.Failed
                }
            }
            if (tasks.isEmpty()) Text(AdministrativeCopy.Empty.text(locale), Modifier.padding(24.dp))
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
    Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        QueueFilter.entries.forEach { item ->
            val label = when (item) {
                QueueFilter.All -> AdministrativeCopy.All
                QueueFilter.Running -> AdministrativeCopy.Running
                QueueFilter.Failed -> AdministrativeCopy.Failed
            }
            FilterChip(filter == item, { onSelect(item) }, { Text(label.text(locale)) })
        }
    }
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
    Column(Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onMore).padding(horizontal = 16.dp, vertical = 12.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column(Modifier.weight(1f)) {
                Text(task.title, style = MaterialTheme.typography.titleMedium)
                Text(task.maskedRecipient, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(task.status.copy().text(locale), color = task.status.color())
        }
        task.progress?.let { progress ->
            val animatedProgress = rememberForwardProgress(progress, progressIdentity = task.id)
            LinearProgressIndicator(progress = { animatedProgress }, Modifier.fillMaxWidth().padding(top = 8.dp))
        }
        task.statusCode?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            if (task.status in setOf(QueueStatus.Queued, QueueStatus.Running)) TextButton(onClick = onCancel) { Text(AdministrativeCopy.CancelTask.text(locale)) }
            if (task.status == QueueStatus.Failed) TextButton(onClick = onRetry) { Text(AdministrativeCopy.RetryTask.text(locale)) }
            if (task.status in setOf(QueueStatus.Completed, QueueStatus.Failed, QueueStatus.Cancelled)) {
                TextButton(onClick = onDelete) { Text(AdministrativeCopy.Delete.text(locale), color = MaterialTheme.colorScheme.error) }
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
        toolbarActions = { IconButton({ onNavigate(AdministrativeSettingsRoute.UserEdit()) }) { Icon(Icons.Outlined.PersonAdd, AdministrativeCopy.AddUser.text(locale)) } },
    ) {
        AdministrativeTextField(search, { search = it }, AdministrativeCopy.Search, locale, textAlign = TextAlign.Start)
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(enabledFilter == null, { enabledFilter = null }, { Text(AdministrativeCopy.All.text(locale)) })
            FilterChip(enabledFilter == true, { enabledFilter = true }, { Text(AdministrativeCopy.Enabled.text(locale)) })
            FilterChip(enabledFilter == false, { enabledFilter = false }, { Text(AdministrativeCopy.Disabled.text(locale)) })
        }
        PageStateContent(state, locale, onRetry) { snapshot ->
            snapshot.users.filter { user ->
                (search.isBlank() || user.displayName.contains(search, true) || user.email.contains(search, true)) &&
                    (enabledFilter == null || user.enabled == enabledFilter)
            }.forEach { user ->
                ListItem(
                    headlineContent = { Text(user.displayName) },
                    supportingContent = { Text("${user.email}\n${user.role.copy().text(locale)}") },
                    trailingContent = {
                        Row {
                            Text(if (user.enabled) AdministrativeCopy.Enabled.text(locale) else AdministrativeCopy.Disabled.text(locale))
                            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null)
                        }
                    },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                    modifier = Modifier.fillMaxWidth().clickable(role = Role.Button) { onNavigate(AdministrativeSettingsRoute.UserEdit(user.id)) },
                )
                AdministrativeDivider()
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
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var showReset by remember { mutableStateOf(false) }
    var showDelete by remember { mutableStateOf(false) }
    val snapshot = state.snapshot
    val user = snapshot?.user
    var displayName by remember(user) { mutableStateOf(user?.displayName.orEmpty()) }
    var email by remember(user) { mutableStateOf(user?.email.orEmpty()) }
    var role by remember(user) { mutableStateOf(user?.role ?: UserRole.Member) }
    var enabled by remember(user) { mutableStateOf(user?.enabled ?: true) }
    var userLocale by remember(user) { mutableStateOf(user?.locale ?: AdministrativeLocale.EnUs) }
    var initialPassword by remember(user) { mutableStateOf("") }
    var canManageSystem by remember(snapshot) { mutableStateOf(snapshot?.canManageSystem ?: false) }
    var canViewManualImports by remember(snapshot) { mutableStateOf(snapshot?.canViewManualImports ?: false) }
    val hasChanges = snapshot?.let { initial ->
        val initialUser = initial.user
        initialUser == null ||
            displayName.trim() != initialUser.displayName.trim() ||
            email.trim() != initialUser.email.trim() ||
            role != initialUser.role ||
            enabled != initialUser.enabled ||
            userLocale != initialUser.locale ||
            canManageSystem != initial.canManageSystem ||
            canViewManualImports != initial.canViewManualImports ||
            initialPassword.isNotBlank()
    } == true
    val canSave = snapshot != null && !state.mutationInFlight && hasChanges &&
        displayName.isNotBlank() && email.isNotBlank() && (user != null || initialPassword.length in 10..128)
    AdministrativePage(
        title = if (user == null) AdministrativeCopy.NewUser else AdministrativeCopy.EditUser,
        locale = locale,
        onBack = onBack,
        modifier = modifier,
        toolbarActions = {
            AdministrativeSaveAction(
                label = AdministrativeCopy.SaveUser,
                locale = locale,
                enabled = canSave,
                working = state.mutationInFlight,
                onClick = {
                    snapshot?.let { current ->
                        onCommand(
                            AdministrativeCommand.SaveUser(
                                UserDraft(
                                    current.user?.id,
                                    displayName.trim(),
                                    email.trim(),
                                    role,
                                    enabled,
                                    initialPassword.ifBlank { null },
                                    canManageSystem,
                                    canViewManualImports,
                                    current.selectedSourceIds,
                                    userLocale,
                                ),
                            ),
                        )
                    }
                },
            )
        },
    ) {
        PageStateContent(state, locale, onRetry) { current ->
            AdministrativeSection(AdministrativeCopy.Users, locale)
            AdministrativeTextField(displayName, { displayName = it }, AdministrativeCopy.DisplayName, locale)
            AdministrativeTextField(email, { email = it }, AdministrativeCopy.Email, locale)
            EnumChoiceRow(AdministrativeCopy.Role, UserRole.entries, role, { role = it }, locale) { it.copy().text(locale) }
            EnumChoiceRow(AdministrativeCopy.Language, AdministrativeLocale.entries, userLocale, { userLocale = it }, locale) {
                when (it) { AdministrativeLocale.ZhCn -> "简体中文"; AdministrativeLocale.EnUs -> "English (United States)" }
            }
            if (current.user != null) {
                AdministrativeNavigationRow(
                    AdministrativeCopy.AccessScope.text(locale),
                    if (current.canManageSystem) AdministrativeCopy.AllLibraries.text(locale) else "${current.selectedSourceIds.size} ${AdministrativeCopy.Items.text(locale)}",
                    { onNavigate(AdministrativeSettingsRoute.UserAccess(current.user.id)) },
                )
                AdministrativeSection(AdministrativeCopy.AccountStatus, locale)
                AdministrativeSwitchRow(AdministrativeCopy.EnableAccount.text(locale), enabled, { enabled = it })
                TextButton(onClick = { showReset = true }, modifier = Modifier.fillMaxWidth()) { Text(AdministrativeCopy.ResetPassword.text(locale)) }
            } else {
                AdministrativeTextField(initialPassword, { initialPassword = it }, AdministrativeCopy.Password, locale, password = true)
            }
            AdministrativeSwitchRow(AdministrativeCopy.System.text(locale), canManageSystem, { canManageSystem = it }, supporting = "canManageSystem")
            AdministrativeSwitchRow(AdministrativeCopy.ImportTasks.text(locale), canViewManualImports, { canViewManualImports = it })
            if (current.user != null) DangerousAction(AdministrativeCopy.DeleteUser, locale, !state.mutationInFlight) { showDelete = true }
            if (showReset) ResetPasswordDialog(current.user?.id.orEmpty(), locale, onCommand) { showReset = false }
            if (showDelete) AdministrativeConfirmDialog(
                AdministrativeCopy.DeleteUserTitle, AdministrativeCopy.DeleteUserBody, AdministrativeCopy.DeleteUser, locale,
                onConfirm = { showDelete = false; onCommand(AdministrativeCommand.DeleteUser(current.user?.id.orEmpty())) },
                onDismiss = { showDelete = false },
            )
        }
    }
}

@Composable
private fun ResetPasswordDialog(
    userId: String,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onDismiss: () -> Unit,
) {
    var password by remember { mutableStateOf("") }
    var confirmation by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(AdministrativeCopy.ResetPassword.text(locale)) },
        text = {
            Column {
                SettingsTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = AdministrativeCopy.NewPassword.text(locale),
                    password = true,
                )
                SettingsTextField(
                    value = confirmation,
                    onValueChange = { confirmation = it },
                    label = AdministrativeCopy.ConfirmPassword.text(locale),
                    password = true,
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = password.length >= 8 && password == confirmation,
                onClick = { onDismiss(); onCommand(AdministrativeCommand.ResetUserPassword(userId, password)) },
            ) { Text(AdministrativeCopy.ResetAndRequireLogin.text(locale)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(AdministrativeCopy.Cancel.text(locale)) } },
    )
}

@Composable
fun UserAccessScreen(
    state: AdministrativePageState<UserAccessSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val snapshot = state.snapshot
    var allLibraries by remember(snapshot) { mutableStateOf(snapshot?.allLibraries ?: false) }
    var selected by remember(snapshot) {
        mutableStateOf(snapshot?.sources?.filter(AccessSource::selected)?.map(AccessSource::id)?.toSet().orEmpty())
    }
    val hasChanges = snapshot?.let {
        allLibraries != it.allLibraries || selected != it.sources.filter(AccessSource::selected).map(AccessSource::id).toSet()
    } == true
    val canSave = snapshot != null && !state.mutationInFlight && hasChanges && (allLibraries || selected.isNotEmpty())
    AdministrativePage(
        title = AdministrativeCopy.AccessScope,
        locale = locale,
        onBack = onBack,
        modifier = modifier,
        toolbarActions = {
            AdministrativeSaveAction(
                label = AdministrativeCopy.SaveAccessScope,
                locale = locale,
                enabled = canSave,
                working = state.mutationInFlight,
                onClick = {
                    snapshot?.let {
                        onCommand(AdministrativeCommand.SaveUserAccess(it.user.id, allLibraries, selected))
                    }
                },
            )
        },
    ) {
        PageStateContent(state, locale, onRetry) { current ->
            ListItem(
                headlineContent = { Text(current.user.displayName) },
                supportingContent = { Text(current.user.email) },
                colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
            )
            AdministrativeSwitchRow(AdministrativeCopy.AllLibraries.text(locale), allLibraries, { allLibraries = it })
            current.sources.forEach { source ->
                AdministrativeSwitchRow(
                    source.name,
                    allLibraries || selected.contains(source.id),
                    { checked -> selected = if (checked) selected + source.id else selected - source.id },
                    source.workCount?.let { "${source.path} · $it ${AdministrativeCopy.Works.text(locale)}" } ?: source.path,
                    enabled = !allLibraries,
                )
            }
            Text(AdministrativeCopy.UserAccessHint.text(locale), Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
