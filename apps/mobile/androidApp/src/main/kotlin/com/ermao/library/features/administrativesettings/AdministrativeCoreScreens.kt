package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ListAlt
import androidx.compose.material.icons.automirrored.outlined.MergeType
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Backup
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Email
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material.icons.outlined.HealthAndSafety
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.ManageAccounts
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Reorder
import androidx.compose.material.icons.outlined.SettingsSuggest
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material3.FilterChip
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ermao.library.ui.components.SettingsTabRow
import com.ermao.library.ui.components.SettingsTextField

@Composable
fun ManagementIndexScreen(
    state: AdministrativePageState<ManagementSnapshot>,
    locale: AdministrativeLocale,
    capabilities: Set<AdministrativeCapability>,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.Management, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            val mobileEntries = snapshot.entries.filterNot { it.route.isRetiredMobileRoute() }
            ManagementGroup(AdministrativeCopy.Library, mobileEntries.filter { it.route.group() == ManagementGroup.Library }, locale, capabilities, onNavigate)
            ManagementGroup(AdministrativeCopy.Services, mobileEntries.filter { it.route.group() == ManagementGroup.Services }, locale, capabilities, onNavigate)
            ManagementGroup(AdministrativeCopy.System, mobileEntries.filter { it.route.group() == ManagementGroup.System }, locale, capabilities, onNavigate)
        }
    }
}

@Composable
private fun ManagementGroup(
    title: AdministrativeCopy,
    entries: List<ManagementEntry>,
    locale: AdministrativeLocale,
    capabilities: Set<AdministrativeCapability>,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
) {
    if (entries.isEmpty()) return
    AdministrativeSection(title, locale)
    entries.forEach { entry ->
        val allowed = capabilities.contains(entry.route.requiredCapability())
        if (allowed) {
            AdministrativeNavigationRow(
                title = entry.route.title().text(locale),
                summary = entry.status,
                onClick = { onNavigate(entry.route) },
                leading = entry.route.icon(),
                attention = entry.attention,
            )
        }
    }
}

private enum class ManagementGroup { Library, Services, System }

private fun AdministrativeSettingsRoute.group(): ManagementGroup = when (this) {
    AdministrativeSettingsRoute.LibrarySources,
    is AdministrativeSettingsRoute.LibrarySourceEdit,
    is AdministrativeSettingsRoute.ServerDirectory,
    AdministrativeSettingsRoute.ImportTasks,
    is AdministrativeSettingsRoute.ImportTaskDetail,
    AdministrativeSettingsRoute.ImportScanJobs,
    is AdministrativeSettingsRoute.ImportScanJob,
    AdministrativeSettingsRoute.ImportPreferences,
    AdministrativeSettingsRoute.OrganizeQueue,
    AdministrativeSettingsRoute.OrganizeCandidates,
    AdministrativeSettingsRoute.OrganizeRuns,
    AdministrativeSettingsRoute.RecognitionPolicy,
    AdministrativeSettingsRoute.LibraryOperations,
    is AdministrativeSettingsRoute.CategoryGovernance,
    AdministrativeSettingsRoute.MetadataProviders,
    is AdministrativeSettingsRoute.MetadataProviderEdit,
    -> ManagementGroup.Library
    is AdministrativeSettingsRoute.EmailKindle,
    AdministrativeSettingsRoute.KindleQueue,
    AdministrativeSettingsRoute.Users,
    is AdministrativeSettingsRoute.UserEdit,
    is AdministrativeSettingsRoute.UserAccess,
    AdministrativeSettingsRoute.Opds,
    -> ManagementGroup.Services
    AdministrativeSettingsRoute.Root,
    AdministrativeSettingsRoute.Backups,
    AdministrativeSettingsRoute.DetailOrder,
    is AdministrativeSettingsRoute.Health,
    AdministrativeSettingsRoute.Logs,
    -> ManagementGroup.System
}

private fun AdministrativeSettingsRoute.title(): AdministrativeCopy = when (this) {
    AdministrativeSettingsRoute.Root -> AdministrativeCopy.Management
    is AdministrativeSettingsRoute.EmailKindle -> AdministrativeCopy.EmailAndKindle
    AdministrativeSettingsRoute.KindleQueue -> AdministrativeCopy.KindleQueue
    AdministrativeSettingsRoute.Users,
    is AdministrativeSettingsRoute.UserEdit,
    is AdministrativeSettingsRoute.UserAccess,
    -> AdministrativeCopy.UsersAndPermissions
    AdministrativeSettingsRoute.LibrarySources,
    is AdministrativeSettingsRoute.LibrarySourceEdit,
    is AdministrativeSettingsRoute.ServerDirectory,
    -> AdministrativeCopy.LibrarySources
    AdministrativeSettingsRoute.ImportTasks -> AdministrativeCopy.ImportTasks
    is AdministrativeSettingsRoute.ImportTaskDetail -> AdministrativeCopy.ImportTaskDetail
    AdministrativeSettingsRoute.ImportScanJobs,
    is AdministrativeSettingsRoute.ImportScanJob,
    -> AdministrativeCopy.ScanJobs
    AdministrativeSettingsRoute.ImportPreferences -> AdministrativeCopy.ImportPreferences
    AdministrativeSettingsRoute.OrganizeQueue,
    AdministrativeSettingsRoute.OrganizeCandidates,
    AdministrativeSettingsRoute.OrganizeRuns,
    -> AdministrativeCopy.SmartOrganization
    AdministrativeSettingsRoute.RecognitionPolicy -> AdministrativeCopy.RecognitionPolicy
    AdministrativeSettingsRoute.LibraryOperations -> AdministrativeCopy.OperationHistory
    is AdministrativeSettingsRoute.CategoryGovernance -> AdministrativeCopy.CategoryGovernance
    AdministrativeSettingsRoute.MetadataProviders,
    is AdministrativeSettingsRoute.MetadataProviderEdit,
    -> AdministrativeCopy.MetadataProviders
    AdministrativeSettingsRoute.Opds -> AdministrativeCopy.Opds
    AdministrativeSettingsRoute.Backups -> AdministrativeCopy.DataAndBackups
    AdministrativeSettingsRoute.DetailOrder -> AdministrativeCopy.WorkDetailOrder
    is AdministrativeSettingsRoute.Health -> AdministrativeCopy.SystemHealth
    AdministrativeSettingsRoute.Logs -> AdministrativeCopy.SystemLogs
}

private fun AdministrativeSettingsRoute.icon(): ImageVector = when (this) {
    AdministrativeSettingsRoute.LibrarySources, is AdministrativeSettingsRoute.LibrarySourceEdit, is AdministrativeSettingsRoute.ServerDirectory -> Icons.Outlined.Folder
    AdministrativeSettingsRoute.ImportTasks, is AdministrativeSettingsRoute.ImportTaskDetail,
    AdministrativeSettingsRoute.ImportScanJobs, is AdministrativeSettingsRoute.ImportScanJob,
    -> Icons.Outlined.Download
    AdministrativeSettingsRoute.ImportPreferences -> Icons.Outlined.Tune
    AdministrativeSettingsRoute.OrganizeQueue, AdministrativeSettingsRoute.OrganizeCandidates,
    AdministrativeSettingsRoute.OrganizeRuns,
    -> Icons.Outlined.SettingsSuggest
    AdministrativeSettingsRoute.RecognitionPolicy -> Icons.Outlined.Tune
    AdministrativeSettingsRoute.LibraryOperations, is AdministrativeSettingsRoute.CategoryGovernance,
    -> Icons.AutoMirrored.Outlined.MergeType
    AdministrativeSettingsRoute.MetadataProviders, is AdministrativeSettingsRoute.MetadataProviderEdit -> Icons.Outlined.Storage
    AdministrativeSettingsRoute.Users, is AdministrativeSettingsRoute.UserEdit, is AdministrativeSettingsRoute.UserAccess -> Icons.Outlined.ManageAccounts
    is AdministrativeSettingsRoute.EmailKindle -> Icons.Outlined.Email
    AdministrativeSettingsRoute.KindleQueue -> Icons.AutoMirrored.Outlined.Send
    AdministrativeSettingsRoute.Opds -> Icons.Outlined.Dns
    AdministrativeSettingsRoute.Backups -> Icons.Outlined.Backup
    AdministrativeSettingsRoute.DetailOrder -> Icons.Outlined.Reorder
    is AdministrativeSettingsRoute.Health -> Icons.Outlined.HealthAndSafety
    AdministrativeSettingsRoute.Logs -> Icons.AutoMirrored.Outlined.ListAlt
    AdministrativeSettingsRoute.Root -> Icons.Outlined.SettingsSuggest
}

@Composable
fun EmailKindleSettingsScreen(
    selectedTab: EmailKindleTab,
    state: AdministrativePageState<EmailKindleSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var selectedTabName by rememberSaveable { mutableStateOf(selectedTab.name) }
    val activeTab = EmailKindleTab.entries.firstOrNull { it.name == selectedTabName } ?: EmailKindleTab.Kindle
    val snapshot = state.snapshot
    var kindleRecipient by remember(snapshot?.kindle?.recipient) {
        mutableStateOf(snapshot?.kindle?.recipient.orEmpty())
    }
    var smtpForm by remember(snapshot?.smtp) {
        mutableStateOf(SmtpFormState.from(snapshot?.smtp))
    }
    val kindleChanged = snapshot?.kindle?.let {
        kindleRecipient.trim() != it.recipient.trim()
    } == true
    val smtpChanged = snapshot?.smtp?.let { smtpForm.hasChangesFrom(it) } ?: false
    val smtpValid = smtpForm.host.isNotBlank() && smtpForm.senderEmail.isNotBlank() &&
        (smtpForm.port.toIntOrNull() ?: 0) in 1..65535
    val canSave = !state.mutationInFlight && snapshot != null && when (activeTab) {
        EmailKindleTab.Kindle -> kindleRecipient.isNotBlank() && kindleChanged
        EmailKindleTab.Smtp -> smtpValid && smtpChanged
    }
    AdministrativePage(
        title = AdministrativeCopy.EmailAndKindle,
        locale = locale,
        onBack = onBack,
        modifier = modifier,
        toolbarActions = {
            AdministrativeSaveAction(
                label = if (activeTab == EmailKindleTab.Kindle) AdministrativeCopy.SaveKindle else AdministrativeCopy.SaveSmtp,
                locale = locale,
                enabled = canSave,
                working = state.mutationInFlight,
                onClick = {
                    when (activeTab) {
                        EmailKindleTab.Kindle -> snapshot?.let {
                            onCommand(AdministrativeCommand.SaveKindle(it.kindle.copy(recipient = kindleRecipient.trim())))
                        }
                        EmailKindleTab.Smtp -> if (smtpValid) {
                            onCommand(AdministrativeCommand.SaveSmtp(smtpForm.toDraft()))
                        }
                    }
                },
            )
        },
    ) {
        SettingsTabRow(
            selectedIndex = if (activeTab == EmailKindleTab.Kindle) 0 else 1,
            tabs = buildList {
                add(AdministrativeCopy.Kindle.text(locale))
                if (snapshot?.canManageSmtp == true || activeTab == EmailKindleTab.Smtp) {
                    add(AdministrativeCopy.Smtp.text(locale))
                }
            },
            enabled = !state.mutationInFlight,
            onSelect = { index ->
                selectedTabName = if (index == 0) EmailKindleTab.Kindle.name else EmailKindleTab.Smtp.name
            },
            modifier = Modifier.fillMaxWidth(),
        )
        PageStateContent(state, locale, onRetry) { current ->
            if (activeTab == EmailKindleTab.Kindle) {
                KindleSettingsForm(
                    initial = current.kindle,
                    recipient = kindleRecipient,
                    onRecipientChanged = { kindleRecipient = it },
                    locale = locale,
                )
            } else {
                current.smtp?.let {
                    SmtpSettingsForm(
                        initial = it,
                        form = smtpForm,
                        onFormChanged = { smtpForm = it },
                        locale = locale,
                        saving = state.mutationInFlight,
                        onCommand = onCommand,
                    )
                }
            }
        }
    }
}

private data class SmtpFormState(
    val host: String,
    val port: String,
    val encryption: SmtpEncryption,
    val senderEmail: String,
    val username: String,
    val password: String,
    val senderName: String,
    val maximumAttachment: String,
) {
    fun toDraft(): SmtpSettingsDraft = SmtpSettingsDraft(
        host = host.trim(),
        port = port.toIntOrNull() ?: 0,
        encryption = encryption,
        senderEmail = senderEmail.trim(),
        username = username.trim(),
        newPassword = password.ifBlank { null },
        senderName = senderName.trim(),
        maximumAttachmentMegabytes = maximumAttachment.toDoubleOrNull(),
    )

    fun hasChangesFrom(initial: SmtpSettings): Boolean =
        host.trim() != initial.host.trim() ||
            (port.toIntOrNull() ?: 0) != initial.port ||
            encryption != initial.encryption ||
            senderEmail.trim() != initial.senderEmail.trim() ||
            username.trim() != initial.username.trim() ||
            password.isNotBlank() ||
            senderName.trim() != initial.senderName.trim() ||
            maximumAttachment.toDoubleOrNull() != initial.maximumAttachmentMegabytes

    companion object {
        fun from(initial: SmtpSettings?): SmtpFormState = SmtpFormState(
            host = initial?.host.orEmpty(),
            port = initial?.port?.toString().orEmpty(),
            encryption = initial?.encryption ?: SmtpEncryption.StartTls,
            senderEmail = initial?.senderEmail.orEmpty(),
            username = initial?.username.orEmpty(),
            password = "",
            senderName = initial?.senderName.orEmpty(),
            maximumAttachment = initial?.maximumAttachmentMegabytes?.toString().orEmpty(),
        )
    }
}

@Composable
private fun ColumnScope.KindleSettingsForm(
    initial: KindleSettings,
    recipient: String,
    onRecipientChanged: (String) -> Unit,
    locale: AdministrativeLocale,
) {
    AdministrativeSection(AdministrativeCopy.KindleRecipient, locale)
    AdministrativeTextField(recipient, onRecipientChanged, AdministrativeCopy.Email, locale)
    AdministrativeValueRow(AdministrativeCopy.Smtp.text(locale), if (initial.smtpConfigured) AdministrativeCopy.Enabled.text(locale) else AdministrativeCopy.Disabled.text(locale))
    AdministrativeValueRow(AdministrativeCopy.SenderEmail.text(locale), initial.senderEmail)
}

@Composable
private fun ColumnScope.SmtpSettingsForm(
    initial: SmtpSettings,
    form: SmtpFormState,
    onFormChanged: (SmtpFormState) -> Unit,
    locale: AdministrativeLocale,
    saving: Boolean,
    onCommand: (AdministrativeCommand) -> Unit,
) {
    AdministrativeTextField(form.host, { onFormChanged(form.copy(host = it)) }, AdministrativeCopy.SmtpHost, locale)
    AdministrativeTextField(form.port, { onFormChanged(form.copy(port = it.filter(Char::isDigit))) }, AdministrativeCopy.Port, locale)
    EnumChoiceRow(AdministrativeCopy.Encryption, SmtpEncryption.entries, form.encryption, { onFormChanged(form.copy(encryption = it)) }, locale) { it.name }
    AdministrativeTextField(form.senderEmail, { onFormChanged(form.copy(senderEmail = it)) }, AdministrativeCopy.SenderEmail, locale)
    AdministrativeTextField(form.username, { onFormChanged(form.copy(username = it)) }, AdministrativeCopy.Username, locale)
    AdministrativeTextField(form.senderName, { onFormChanged(form.copy(senderName = it)) }, AdministrativeCopy.DisplayName, locale)
    AdministrativeTextField(form.maximumAttachment, { onFormChanged(form.copy(maximumAttachment = it)) }, AdministrativeCopy.FileFormat, locale)
    SettingsTextField(
        value = form.password,
        onValueChange = { onFormChanged(form.copy(password = it)) },
        label = AdministrativeCopy.Password.text(locale),
        placeholder = if (initial.passwordConfigured) AdministrativeCopy.PasswordUnchanged.text(locale) else null,
        password = true,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
    )
    initial.lastTest?.let {
        ListItem(
            headlineContent = { Text(if (it.successful) AdministrativeCopy.SmtpTestSucceeded.text(locale) else AdministrativeCopy.OperationFailed.text(locale)) },
            supportingContent = it.latencyMilliseconds?.let { latency -> ({ Text("$latency ms") }) },
            colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
        )
    }
    val valid = form.host.isNotBlank() && form.senderEmail.isNotBlank() && (form.port.toIntOrNull() ?: 0) in 1..65535
    TextButton(onClick = { onCommand(AdministrativeCommand.TestSmtp(form.toDraft())) }, enabled = !saving && valid, modifier = Modifier.fillMaxWidth()) {
        Text(AdministrativeCopy.SendTestEmail.text(locale))
    }
}

@Composable
internal fun AdministrativeTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: AdministrativeCopy,
    locale: AdministrativeLocale,
    password: Boolean = false,
    supporting: String? = null,
    textAlign: TextAlign = TextAlign.End,
) {
    SettingsTextField(
        value = value,
        onValueChange = onValueChange,
        label = label.text(locale),
        supportingText = supporting,
        password = password,
        textAlign = textAlign,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
    )
}

@Composable
internal fun <T> EnumChoiceRow(
    label: AdministrativeCopy,
    values: List<T>,
    selected: T,
    onSelect: (T) -> Unit,
    locale: AdministrativeLocale,
    valueText: (T) -> String,
) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text(label.text(locale), style = MaterialTheme.typography.labelLarge)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            values.forEach { value ->
                FilterChip(selected == value, { onSelect(value) }, { Text(valueText(value)) })
            }
        }
    }
}
