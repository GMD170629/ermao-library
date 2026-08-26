package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
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
    val states by viewModel.states.collectAsState()
    val state = states[route] ?: AdministrativeScreenState()
    LaunchedEffect(route) { viewModel.load(route) }
    LaunchedEffect(route, state.snapshot) {
        if ((state.snapshot as? ImportScanJobSnapshot)?.job?.active == true ||
            (state.snapshot as? HealthSnapshot)?.let { it.status == HealthStatus.Checking } == true
        ) viewModel.poll(route)
    }
    LaunchedEffect(viewModel) {
        viewModel.effects.collectLatest { effect ->
            if (effect is AdministrativeSettingsEffect.ExportReady) systemActions.saveExport(effect.file)
            onEffect(effect)
        }
    }
    when (route) {
        AdministrativeSettingsRoute.Root -> ManagementIndexScreen(
            state.typed(), locale, capabilities, onNavigate, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.EmailKindle -> EmailKindleSettingsScreen(
            route.tab, state.typed(), locale,
            onTabSelected = { onReplace(AdministrativeSettingsRoute.EmailKindle(it)) },
            onCommand = viewModel::execute, onRetry = { viewModel.load(route, true) }, onBack = onBack, modifier = modifier,
        )
        AdministrativeSettingsRoute.KindleQueue -> KindleQueueScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        AdministrativeSettingsRoute.Users -> UsersScreen(
            state.typed(), locale, onNavigate, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.UserEdit -> UserEditScreen(
            state.typed(), locale, onNavigate, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
        )
        is AdministrativeSettingsRoute.UserAccess -> UserAccessScreen(
            state.typed(), locale, viewModel::execute, { viewModel.load(route, true) }, onBack, modifier,
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
}

@Suppress("UNCHECKED_CAST")
private fun <T : AdministrativePageSnapshot> AdministrativeScreenState.typed(): AdministrativePageState<T> =
    AdministrativePageState(phase, snapshot as? T, failure, mutationInFlight)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun AdministrativePage(
    title: AdministrativeCopy,
    locale: AdministrativeLocale,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    toolbarActions: @Composable () -> Unit = {},
    content: @Composable ColumnScope.() -> Unit,
) {
    val theme = WarmPageThemeValues
    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text(title.text(locale)) },
                navigationIcon = {
                    IconButton(onClick = onBack, modifier = Modifier.testTag("administrative-back")) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, AdministrativeCopy.NavigateBack.text(locale))
                    }
                },
                actions = { toolbarActions() },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = theme.colors.canvas),
            )
        },
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
        AdministrativeStateMessage(Icons.Outlined.Lock, AdministrativeCopy.PermissionDenied.text(locale), null)
        return
    }
    if (snapshot == null && state.phase == AdministrativePagePhase.Loading) {
        Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(Modifier.testTag("administrative-loading"))
        }
        return
    }
    if (snapshot == null && state.phase == AdministrativePagePhase.Failure) {
        AdministrativeStateMessage(
            Icons.Outlined.ErrorOutline,
            failureText(state.failure, locale),
            if (state.failure?.retryable == true) onRetry else null,
        )
        return
    }
    if (snapshot == null) return
    if (state.failure != null) InlineAdministrativeFailure(state.failure, locale, onRetry)
    content(snapshot)
}

@Composable
private fun AdministrativeStateMessage(icon: ImageVector, text: String, onRetry: (() -> Unit)?) {
    Column(
        Modifier.fillMaxWidth().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Icon(icon, contentDescription = null)
        Text(text)
        onRetry?.let { OutlinedButton(onClick = it) { Text(AdministrativeCopy.Retry.text(guessLocale(text))) } }
    }
}

@Composable
private fun InlineAdministrativeFailure(
    failure: AdministrativeFailure,
    locale: AdministrativeLocale,
    onRetry: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(failureText(failure, locale), color = MaterialTheme.colorScheme.error, modifier = Modifier.weight(1f))
        if (failure.retryable) TextButton(onClick = onRetry) { Text(AdministrativeCopy.Retry.text(locale)) }
    }
}

private fun guessLocale(text: String): AdministrativeLocale =
    if (text.any { it.code in 0x4E00..0x9FFF }) AdministrativeLocale.ZhCn else AdministrativeLocale.EnUs

internal fun failureText(failure: AdministrativeFailure?, locale: AdministrativeLocale): String = when (failure?.kind) {
    AdministrativeErrorKind.Forbidden -> AdministrativeCopy.PermissionDenied.text(locale)
    AdministrativeErrorKind.Unauthorized -> AdministrativeCopy.SessionExpired.text(locale)
    else -> AdministrativeCopy.OperationFailed.text(locale)
}

@Composable
internal fun AdministrativeSection(title: AdministrativeCopy, locale: AdministrativeLocale) {
    Text(
        title.text(locale),
        style = WarmPageThemeValues.typography.label,
        color = WarmPageThemeValues.colors.textSecondary,
        modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 8.dp).semantics { heading() },
    )
}

@Composable
internal fun AdministrativeNavigationRow(
    title: String,
    summary: String?,
    onClick: () -> Unit,
    leading: ImageVector? = null,
    attention: Boolean = false,
) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = summary?.let { ({ Text(it) }) },
        leadingContent = leading?.let { icon -> ({ Icon(icon, null) }) },
        trailingContent = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (attention) Text("●", color = MaterialTheme.colorScheme.error)
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null)
            }
        },
        colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(role = Role.Button, onClick = onClick),
    )
    AdministrativeDivider(if (leading == null) 16.dp else 56.dp)
}

@Composable
internal fun AdministrativeValueRow(
    label: String,
    value: String,
    supporting: String? = null,
    onClick: (() -> Unit)? = null,
) {
    val clickModifier = if (onClick == null) Modifier else Modifier.clickable(role = Role.Button, onClick = onClick)
    ListItem(
        headlineContent = { Text(label) },
        supportingContent = supporting?.let { ({ Text(it) }) },
        trailingContent = { Text(value, color = WarmPageThemeValues.colors.textSecondary) },
        colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).then(clickModifier),
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
    ListItem(
        headlineContent = { Text(label) },
        supportingContent = supporting?.let { ({ Text(it) }) },
        trailingContent = {
            Switch(checked = checked, onCheckedChange = null, enabled = enabled)
        },
        colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(
            enabled = enabled,
            role = Role.Switch,
            onClick = { onCheckedChange(!checked) },
        ),
    )
    AdministrativeDivider()
}

@Composable
internal fun AdministrativeDivider(start: androidx.compose.ui.unit.Dp = 16.dp) {
    HorizontalDivider(Modifier.padding(start = start), color = WarmPageThemeValues.colors.divider)
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
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).padding(horizontal = 16.dp, vertical = 8.dp),
    ) { Text(label.text(locale), color = MaterialTheme.colorScheme.error) }
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
            TextButton(onClick = onConfirm) { Text(confirm.text(locale), color = MaterialTheme.colorScheme.error) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(AdministrativeCopy.Cancel.text(locale)) } },
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
            ListItem(
                headlineContent = {
                    Text(
                        action.label.text(locale),
                        color = if (action.destructive) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
                    )
                },
                modifier = Modifier.fillMaxWidth().clickable(role = Role.Button) {
                    onDismiss()
                    action.onSelect()
                },
            )
        }
        TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
            Text(AdministrativeCopy.Cancel.text(locale))
        }
    }
}

internal data class AdministrativeSheetAction(
    val label: AdministrativeCopy,
    val destructive: Boolean = false,
    val onSelect: () -> Unit,
)
