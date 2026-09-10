package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import com.ermao.library.shared.core.feedback.OperationFeedbackKind
import com.ermao.library.ui.components.rememberWarmPageFeedbackState
import com.ermao.library.ui.components.showFeedback
import com.ermao.library.ui.components.WarmPageSnackbarHost
import kotlinx.coroutines.launch
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.ermao.library.ui.components.SettingsSaveAction
import com.ermao.library.ui.components.WarmPageErrorState
import com.ermao.library.ui.components.WarmPageLoadingState
import com.ermao.library.ui.components.WarmPagePermissionGate
import com.ermao.library.ui.components.WarmSettingsDangerAction
import com.ermao.library.ui.components.WarmSettingsDivider
import com.ermao.library.ui.components.WarmSettingsInlineMessage
import com.ermao.library.ui.components.WarmSettingsNavigationRow
import com.ermao.library.ui.components.WarmSettingsScaffold
import com.ermao.library.ui.components.WarmSettingsScaffoldRole
import com.ermao.library.ui.components.WarmSettingsSection
import com.ermao.library.ui.components.WarmSettingsSwitchRow
import com.ermao.library.ui.components.WarmSettingsValueRow
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.coroutines.flow.collectLatest

interface AdministrativeSettingsSystemActions {
    fun saveExport(file: AdministrativeExportFile)
    fun copyText(text: String)
    fun shareText(text: String)
}

@Composable
fun AdministrativeSettingsDestination(
    route: AdministrativeSettingsRoute,
    viewModel: AdministrativeSettingsViewModel,
    locale: AdministrativeLocale,
    capabilities: Set<AdministrativeCapability>,
    systemActions: AdministrativeSettingsSystemActions,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onReplace: (AdministrativeSettingsRoute) -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    onEffect: (AdministrativeSettingsEffect) -> Unit = {},
) {
    if (route.isRetiredMobileRoute()) return
    val states by viewModel.states.collectAsState()
    val stateRoute = if (route is AdministrativeSettingsRoute.EmailKindle) {
        AdministrativeSettingsRoute.EmailKindle(EmailKindleTab.Kindle)
    } else {
        route
    }
    val state = states[stateRoute] ?: AdministrativeScreenState()
    LaunchedEffect(stateRoute) { viewModel.load(stateRoute) }
    LaunchedEffect(stateRoute, state.snapshot) {
        if ((state.snapshot as? ImportScanJobSnapshot)?.job?.active == true ||
            (state.snapshot as? HealthSnapshot)?.let { it.status == HealthStatus.Checking } == true
        ) viewModel.poll(stateRoute)
    }
    var passwordResetRevision by remember(route) { mutableStateOf(0) }
    val currentRoute by rememberUpdatedState(route)
    val currentOnBack by rememberUpdatedState(onBack)
    val feedbackHost = rememberWarmPageFeedbackState()
    val feedbackScope = rememberCoroutineScope()
    val feedbackLocale by rememberUpdatedState(locale)
    LaunchedEffect(viewModel, route) {
        viewModel.effects.collectLatest { effect ->
            if (effect is AdministrativeSettingsEffect.ExportReady) systemActions.saveExport(effect.file)
            if (effect is AdministrativeSettingsEffect.OperationSucceeded) {
                if (currentRoute is AdministrativeSettingsRoute.UserEdit && effect.ownerRoute == currentRoute) {
                    when (effect.operation) {
                        AdministrativeOperation.SaveUser, AdministrativeOperation.DeleteUser -> currentOnBack()
                        AdministrativeOperation.ResetUserPassword -> passwordResetRevision += 1
                        else -> Unit
                    }
                }
                administrativeSuccessText(effect.operation, feedbackLocale)?.let { message ->
                    feedbackScope.launch { feedbackHost.showFeedback(message, OperationFeedbackKind.Success) }
                }
            }
            onEffect(effect)
        }
    }
    Box(Modifier.fillMaxSize()) {
    when (route) {
        AdministrativeSettingsRoute.Root -> ManagementIndexScreen(
            state.typed(), locale, capabilities, onNavigate, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.EmailKindle -> EmailKindleSettingsScreen(
            route.tab, state.typed(), locale,
            onCommand = viewModel::execute, onRetry = { viewModel.load(stateRoute, true) }, onBack = onBack, modifier = modifier,
        )
        AdministrativeSettingsRoute.KindleQueue -> KindleQueueScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.Users -> UsersScreen(
            state.typed(), locale, onNavigate, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.UserEdit -> UserEditScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier, passwordResetRevision,
        )
        AdministrativeSettingsRoute.LibrarySources -> LibrarySourcesScreen(
            state.typed(), locale, onNavigate,
            onCommand = viewModel::execute, onRetry = { viewModel.load(route, true) }, onBack = onBack, modifier = modifier,
        )
        is AdministrativeSettingsRoute.LibrarySourceEdit -> LibrarySourceEditScreen(
            state.typed(), locale, route.selectedPath, onNavigate, viewModel::execute,
            { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.ServerDirectory -> ServerDirectoryScreen(
            state.typed(), locale, onNavigate, onBack,
            onSelect = { selected ->
                when (route.purpose) {
                    ServerDirectoryPurpose.CreateLibrarySource -> onReplace(
                        AdministrativeSettingsRoute.LibrarySourceEdit(sourceId = null, selectedPath = selected.uri),
                    )
                    is ServerDirectoryPurpose.EditLibrarySource -> onReplace(
                        AdministrativeSettingsRoute.LibrarySourceEdit(sourceId = route.purpose.sourceId, selectedPath = selected.uri),
                    )
                    ServerDirectoryPurpose.ScanDirectory -> viewModel.execute(AdministrativeCommand.ScanDirectory(selected))
                }
            },
            onRetry = { viewModel.load(route, true) }, modifier = modifier,
        )
        AdministrativeSettingsRoute.ImportTasks -> ImportTasksScreen(
            state.typed(), locale, onNavigate, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.ImportTaskDetail -> ImportTaskDetailScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.ImportScanJobs -> ImportScanJobsScreen(
            state.typed(), locale, onNavigate, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.ImportScanJob -> ImportScanJobScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.ImportPreferences -> ImportPreferencesScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.OrganizeQueue -> OrganizeQueueScreen(
            state.typed(), locale, onNavigate, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.OrganizeCandidates -> OrganizeCandidatesScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.OrganizeRuns -> OrganizeRunsScreen(
            state.typed(), locale, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.RecognitionPolicy -> RecognitionPolicyScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.LibraryOperations -> LibraryOperationsScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.CategoryGovernance -> CategoryGovernanceScreen(
            state.typed(), locale, onReplace, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.MetadataProviders -> MetadataProvidersScreen(
            state.typed(), locale, onNavigate, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.MetadataProviderEdit -> MetadataProviderEditScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.Opds -> OpdsScreen(
            state.typed(), locale, systemActions::copyText, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.Backups -> BackupsScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.DetailOrder -> DetailOrderScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.Health -> HealthScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.Logs -> LogsScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
    }
    WarmPageSnackbarHost(feedbackHost, Modifier.align(Alignment.BottomCenter))
    }
}

/** Diagnostic results stay in their existing persistent result rows. */
internal fun administrativeSuccessText(operation: AdministrativeOperation, locale: AdministrativeLocale): String? =
    when (operation) {
        AdministrativeOperation.TestSmtp, AdministrativeOperation.TestMetadataProvider,
        AdministrativeOperation.RunHealthCheck -> null
        AdministrativeOperation.SaveKindle, AdministrativeOperation.SaveSmtp,
        AdministrativeOperation.SaveUser,
        AdministrativeOperation.SaveLibrarySource, AdministrativeOperation.SaveImportPreferences,
        AdministrativeOperation.SaveRecognitionPolicy, AdministrativeOperation.SaveMetadataProviders,
        AdministrativeOperation.SaveMetadataProvider, AdministrativeOperation.SaveOpds,
        AdministrativeOperation.SaveDetailOrder, AdministrativeOperation.SaveLogCapacity -> AdministrativeCopy.Saved.text(locale)
        AdministrativeOperation.RetryKindleTask, AdministrativeOperation.RescanLibrarySource,
        AdministrativeOperation.ScanDirectory, AdministrativeOperation.RetryImportTask,
        AdministrativeOperation.RescanAllSources, AdministrativeOperation.StartRecognition -> AdministrativeCopy.Queued.text(locale)
        else -> AdministrativeCopy.Completed.text(locale)
    }

@Suppress("UNCHECKED_CAST")
private fun <T : AdministrativePageSnapshot> AdministrativeScreenState.typed(): AdministrativePageState<T> =
    AdministrativePageState(phase, snapshot as? T, failure, mutationInFlight)

@Composable
internal fun AdministrativePage(
    title: AdministrativeCopy,
    locale: AdministrativeLocale,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    toolbarActions: @Composable RowScope.() -> Unit = {},
    tabs: (@Composable () -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Detail,
        title = title.text(locale),
        modifier = modifier.testTag("administrative-page-${title.name}"),
        onBack = onBack,
        navigationContentDescription = AdministrativeCopy.NavigateBack.text(locale),
        actions = toolbarActions,
        tabs = tabs,
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()),
            content = content,
        )
    }
}

@Composable
internal fun <T : AdministrativePageSnapshot> ColumnScope.PageStateContent(
    state: AdministrativePageState<T>,
    locale: AdministrativeLocale,
    onRetry: () -> Unit,
    content: @Composable ColumnScope.(T) -> Unit,
) {
    val snapshot = state.snapshot
    if (state.phase == AdministrativePagePhase.PermissionDenied) {
        WarmPagePermissionGate(
            title = AdministrativeCopy.PermissionDenied.text(locale),
            message = AdministrativeCopy.PermissionDeniedHint.text(locale),
            modifier = Modifier.fillMaxWidth(),
        )
        return
    }
    if (snapshot == null && state.phase == AdministrativePagePhase.Loading) {
        WarmPageLoadingState(
            title = AdministrativeCopy.Loading.text(locale),
            modifier = Modifier.fillMaxWidth().testTag("administrative-loading"),
        )
        return
    }
    if (snapshot == null && state.phase == AdministrativePagePhase.Failure) {
        WarmPageErrorState(
            title = AdministrativeCopy.OperationFailed.text(locale),
            message = failureText(state.failure, locale),
            retryLabel = if (state.failure?.retryable == true) AdministrativeCopy.Retry.text(locale) else null,
            onRetry = if (state.failure?.retryable == true) onRetry else null,
            modifier = Modifier.fillMaxWidth(),
        )
        return
    }
    if (snapshot == null) return
    if (state.failure != null) InlineAdministrativeFailure(state.failure, locale, onRetry)
    content(snapshot)
}

@Composable
private fun InlineAdministrativeFailure(
    failure: AdministrativeFailure,
    locale: AdministrativeLocale,
    onRetry: () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        WarmSettingsInlineMessage(
            message = failureText(failure, locale),
            color = MaterialTheme.colorScheme.error,
        )
        if (failure.retryable) {
            OutlinedButton(
                onClick = onRetry,
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) {
                Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(AdministrativeCopy.Retry.text(locale)) }
        }
    }
}

internal fun failureText(failure: AdministrativeFailure?, locale: AdministrativeLocale): String {
    val userMessage = when (failure?.code) {
        "EMAIL_IN_USE" -> if (locale == AdministrativeLocale.ZhCn) "该邮箱已被使用。" else "This email address is already in use."
        "CANNOT_CHANGE_SELF_ADMIN" -> if (locale == AdministrativeLocale.ZhCn) "不能停用或降级当前登录的管理员。" else "You cannot disable or demote the signed-in administrator."
        "LAST_ADMIN_REQUIRED" -> if (locale == AdministrativeLocale.ZhCn) "系统必须至少保留一个有效管理员。" else "At least one active administrator must remain."
        "CANNOT_DELETE_SELF" -> if (locale == AdministrativeLocale.ZhCn) "不能删除当前登录的管理员。" else "You cannot delete the signed-in administrator."
        "DELETE_CONFIRMATION_MISMATCH" -> if (locale == AdministrativeLocale.ZhCn) "确认邮箱不匹配。" else "The confirmation email does not match."
        "INVALID_FOLDER_ACCESS" -> if (locale == AdministrativeLocale.ZhCn) "所选书库权限无效，请重新加载后检查。" else "The selected library grants are invalid. Reload and check them."
        "INVALID_PASSWORD" -> if (locale == AdministrativeLocale.ZhCn) "密码长度须为 10–128 个字符。" else "The password must contain 10–128 characters."
        "INVALID_USER" -> if (locale == AdministrativeLocale.ZhCn) "请检查姓名、邮箱、密码和书库权限。" else "Check the name, email, password and library grants."
        else -> null
    }
    return userMessage ?: when (failure?.kind) {
        AdministrativeErrorKind.Forbidden -> AdministrativeCopy.PermissionDenied.text(locale)
        AdministrativeErrorKind.Unauthorized -> AdministrativeCopy.SessionExpired.text(locale)
        else -> AdministrativeCopy.OperationFailed.text(locale)
    }
}

@Composable
internal fun AdministrativeSection(title: AdministrativeCopy, locale: AdministrativeLocale) {
    WarmSettingsSection(title.text(locale)) {}
}

@Composable
internal fun AdministrativeNavigationRow(
    title: String,
    summary: String?,
    onClick: () -> Unit,
    leading: androidx.compose.ui.graphics.vector.ImageVector? = null,
    attention: Boolean = false,
    testTag: String? = null,
) {
    WarmSettingsNavigationRow(
        title = title,
        summary = if (attention) listOfNotNull(summary, "•").joinToString(" ") else summary,
        icon = leading,
        modifier = testTag?.let(Modifier::testTag) ?: Modifier,
        onClick = onClick,
    )
    AdministrativeDivider(afterIcon = leading != null)
}

@Composable
internal fun AdministrativeValueRow(
    label: String,
    value: String,
    supporting: String? = null,
    onClick: (() -> Unit)? = null,
) {
    WarmSettingsValueRow(
        label = label,
        value = value,
        supporting = supporting,
        onClick = onClick,
    )
    AdministrativeDivider()
}

@Composable
internal fun AdministrativeSwitchRow(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    supporting: String? = null,
    enabled: Boolean = true,
) {
    WarmSettingsSwitchRow(
        label = label,
        checked = checked,
        onCheckedChange = onCheckedChange,
        supporting = supporting,
        enabled = enabled,
    )
    AdministrativeDivider()
}

@Composable
internal fun AdministrativeDivider(afterIcon: Boolean = false) {
    WarmSettingsDivider(afterIcon = afterIcon)
}

@Composable
internal fun AdministrativeSaveAction(
    label: AdministrativeCopy,
    locale: AdministrativeLocale,
    enabled: Boolean,
    working: Boolean,
    onClick: () -> Unit,
) {
    SettingsSaveAction(
        contentDescription = label.text(locale),
        enabled = enabled,
        working = working,
        onClick = onClick,
        modifier = Modifier.testTag("administrative-save-${label.name}"),
        label = AdministrativeCopy.Save.text(locale),
    )
}

@Composable
internal fun PrimaryAction(
    label: AdministrativeCopy,
    locale: AdministrativeLocale,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).padding(horizontal = 16.dp, vertical = 8.dp),
    ) { Text(label.text(locale)) }
}

@Composable
internal fun DangerousAction(
    label: AdministrativeCopy,
    locale: AdministrativeLocale,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    WarmSettingsDangerAction(
        label = label.text(locale),
        enabled = enabled,
        onClick = onClick,
    )
}

@Composable
internal fun AdministrativeConfirmDialog(
    title: AdministrativeCopy,
    body: AdministrativeCopy,
    confirm: AdministrativeCopy,
    locale: AdministrativeLocale,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title.text(locale)) },
        text = { Text(body.text(locale)) },
        confirmButton = {
            OutlinedButton(onClick = onConfirm) {
                Icon(Icons.Outlined.Check, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(confirm.text(locale), color = MaterialTheme.colorScheme.error) }
        },
        dismissButton = { OutlinedButton(onClick = onDismiss) {
            Icon(Icons.Outlined.Close, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(AdministrativeCopy.Cancel.text(locale)) } },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun AdministrativeActionSheet(
    title: String,
    locale: AdministrativeLocale,
    actions: List<AdministrativeSheetAction>,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Text(
            title,
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp),
        )
        actions.forEach { action ->
            OutlinedButton(
                onClick = {
                    onDismiss()
                    action.onSelect()
                },
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) {
                Icon(Icons.Outlined.Settings, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(
                    action.label.text(locale),
                    color = if (action.destructive) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
                )
            }
        }
        OutlinedButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
            Icon(Icons.Outlined.Close, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(AdministrativeCopy.Cancel.text(locale))
        }
    }
}

internal data class AdministrativeSheetAction(
    val label: AdministrativeCopy,
    val destructive: Boolean = false,
    val onSelect: () -> Unit,
)
