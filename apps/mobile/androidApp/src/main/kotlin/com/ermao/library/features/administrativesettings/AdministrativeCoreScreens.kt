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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

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
            ManagementGroup(AdministrativeCopy.Library, snapshot.entries.filter { it.route.group() == ManagementGroup.Library }, locale, capabilities, onNavigate)
            ManagementGroup(AdministrativeCopy.Services, snapshot.entries.filter { it.route.group() == ManagementGroup.Services }, locale, capabilities, onNavigate)
            ManagementGroup(AdministrativeCopy.System, snapshot.entries.filter { it.route.group() == ManagementGroup.System }, locale, capabilities, onNavigate)
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
    is AdministrativeSettingsRoute.MetadataPipeline,
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
    is AdministrativeSettingsRoute.MetadataPipeline -> AdministrativeCopy.MetadataPipeline
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
    AdministrativeSettingsRoute.MetadataProviders, is AdministrativeSettingsRoute.MetadataProviderEdit, is AdministrativeSettingsRoute.MetadataPipeline -> Icons.Outlined.Storage
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
    onTabSelected: (EmailKindleTab) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.EmailAndKindle, locale, onBack, modifier) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            FilterChip(selectedTab == EmailKindleTab.Kindle, { onTabSelected(EmailKindleTab.Kindle) }, { Text(AdministrativeCopy.Kindle.text(locale)) })
            if (state.snapshot?.canManageSmtp == true || selectedTab == EmailKindleTab.Smtp) {
                FilterChip(selectedTab == EmailKindleTab.Smtp, { onTabSelected(EmailKindleTab.Smtp) }, { Text(AdministrativeCopy.Smtp.text(locale)) })
            }
        }
        PageStateContent(state, locale, onRetry) { snapshot ->
            if (selectedTab == EmailKindleTab.Kindle) {
                KindleSettingsForm(snapshot.kindle, locale, state.mutationInFlight, onCommand)
            } else {
                snapshot.smtp?.let { SmtpSettingsForm(it, locale, state.mutationInFlight, onCommand) }
            }
        }
    }
}

@Composable
private fun ColumnScope.KindleSettingsForm(
    initial: KindleSettings,
    locale: AdministrativeLocale,
    saving: Boolean,
    onCommand: (AdministrativeCommand) -> Unit,
) {
    var recipient by remember(initial) { mutableStateOf(initial.recipient) }
    AdministrativeSection(AdministrativeCopy.KindleRecipient, locale)
    AdministrativeTextField(recipient, { recipient = it }, AdministrativeCopy.Email, locale)
    AdministrativeValueRow(AdministrativeCopy.Smtp.text(locale), if (initial.smtpConfigured) AdministrativeCopy.Enabled.text(locale) else AdministrativeCopy.Disabled.text(locale))
    AdministrativeValueRow(AdministrativeCopy.SenderEmail.text(locale), initial.senderEmail)
    PrimaryAction(AdministrativeCopy.SaveKindle, locale, !saving && recipient.isNotBlank()) {
        onCommand(AdministrativeCommand.SaveKindle(initial.copy(recipient = recipient.trim())))
    }
}

@Composable
private fun ColumnScope.SmtpSettingsForm(
    initial: SmtpSettings,
    locale: AdministrativeLocale,
    saving: Boolean,
    onCommand: (AdministrativeCommand) -> Unit,
) {
    var host by remember(initial) { mutableStateOf(initial.host) }
    var portText by remember(initial) { mutableStateOf(initial.port.toString()) }
    var encryption by remember(initial) { mutableStateOf(initial.encryption) }
    var sender by remember(initial) { mutableStateOf(initial.senderEmail) }
    var username by remember(initial) { mutableStateOf(initial.username) }
    var password by remember(initial) { mutableStateOf("") }
    var senderName by remember(initial) { mutableStateOf(initial.senderName) }
    var maximumAttachment by remember(initial) { mutableStateOf(initial.maximumAttachmentMegabytes?.toString().orEmpty()) }
    val draft = {
        SmtpSettingsDraft(
            host.trim(), portText.toIntOrNull() ?: 0, encryption, sender.trim(), username.trim(), password.ifBlank { null },
            senderName.trim(), maximumAttachment.toDoubleOrNull(),
        )
    }
    AdministrativeTextField(host, { host = it }, AdministrativeCopy.SmtpHost, locale)
    AdministrativeTextField(portText, { portText = it.filter(Char::isDigit) }, AdministrativeCopy.Port, locale)
    EnumChoiceRow(AdministrativeCopy.Encryption, SmtpEncryption.entries, encryption, { encryption = it }, locale) { it.name }
    AdministrativeTextField(sender, { sender = it }, AdministrativeCopy.SenderEmail, locale)
    AdministrativeTextField(username, { username = it }, AdministrativeCopy.Username, locale)
    AdministrativeTextField(senderName, { senderName = it }, AdministrativeCopy.DisplayName, locale)
    AdministrativeTextField(maximumAttachment, { maximumAttachment = it }, AdministrativeCopy.FileFormat, locale)
    OutlinedTextField(
        value = password,
        onValueChange = { password = it },
        label = { Text(AdministrativeCopy.Password.text(locale)) },
        placeholder = { if (initial.passwordConfigured) Text(AdministrativeCopy.PasswordUnchanged.text(locale)) },
        visualTransformation = PasswordVisualTransformation(),
        singleLine = true,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
    )
    initial.lastTest?.let {
        ListItem(
            headlineContent = { Text(if (it.successful) AdministrativeCopy.SmtpTestSucceeded.text(locale) else AdministrativeCopy.OperationFailed.text(locale)) },
            supportingContent = it.latencyMilliseconds?.let { latency -> ({ Text("$latency ms") }) },
            colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
        )
    }
    val valid = host.isNotBlank() && sender.isNotBlank() && (portText.toIntOrNull() ?: 0) in 1..65535
    TextButton(onClick = { onCommand(AdministrativeCommand.TestSmtp(draft())) }, enabled = !saving && valid, modifier = Modifier.fillMaxWidth()) {
        Text(AdministrativeCopy.SendTestEmail.text(locale))
    }
    PrimaryAction(AdministrativeCopy.SaveSmtp, locale, !saving && valid) { onCommand(AdministrativeCommand.SaveSmtp(draft())) }
}

@Composable
internal fun AdministrativeTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: AdministrativeCopy,
    locale: AdministrativeLocale,
    password: Boolean = false,
    supporting: String? = null,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label.text(locale)) },
        supportingText = supporting?.let { ({ Text(it) }) },
        visualTransformation = if (password) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        singleLine = true,
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
