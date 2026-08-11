package com.ermao.library.features.servers

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.LockReset
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ermao.library.R
import com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.ui.theme.WarmPageThemeValues

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServerCenterScreen(
    profiles: List<ServerProfileSnapshot>,
    selectedProfileId: String?,
    operationInProgress: Boolean,
    operationErrorCode: String?,
    canClose: Boolean,
    onClose: () -> Unit,
    onAdd: () -> Unit,
    onSelect: (String) -> Unit,
    onCloseDetail: () -> Unit,
    onEdit: (String) -> Unit,
    onSwitch: (String) -> Unit,
    onRemove: (String) -> Unit,
    onRestoreSystemTrust: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val profile = profiles.firstOrNull { it.id == selectedProfileId }
    if (profile != null) {
        ServerDetailScreen(
            profile = profile,
            operationInProgress = operationInProgress,
            operationErrorCode = operationErrorCode,
            onBack = onCloseDetail,
            onEdit = { onEdit(profile.id) },
            onSwitch = { onSwitch(profile.id) },
            onRemove = { onRemove(profile.id) },
            onRestoreSystemTrust = { onRestoreSystemTrust(profile.id) },
            modifier = modifier,
        )
        return
    }

    val theme = WarmPageThemeValues
    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.server_center_title)) },
                navigationIcon = {
                    if (canClose) {
                        IconButton(onClick = onClose) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.navigate_back))
                        }
                    }
                },
                actions = {
                    IconButton(onClick = onAdd, enabled = !operationInProgress) {
                        Icon(Icons.Filled.Add, stringResource(R.string.server_add_title))
                    }
                },
            )
        },
    ) { padding ->
        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding)) {
            item {
                Text(
                    stringResource(R.string.server_center_description),
                    modifier = Modifier.padding(theme.spacing.three),
                    color = theme.colors.textSecondary,
                )
            }
            if (profiles.isEmpty()) {
                item {
                    Column(modifier = Modifier.fillMaxWidth().padding(theme.spacing.three)) {
                        Text(stringResource(R.string.server_center_empty), color = theme.colors.textSecondary)
                        Spacer(Modifier.height(theme.spacing.two))
                        Button(onClick = onAdd) { Text(stringResource(R.string.server_add_title)) }
                    }
                }
            } else {
                items(profiles, key = ServerProfileSnapshot::id) { item ->
                    ListItem(
                        headlineContent = { Text(item.displayName) },
                        supportingContent = { Text(item.baseUrl) },
                        leadingContent = { Icon(Icons.Outlined.Dns, null) },
                        trailingContent = {
                            Column {
                                if (item.isActive) Text(stringResource(R.string.server_active_badge), color = theme.colors.brandAccent)
                                if (item.tlsMode == TlsMode.InsecureSkipAllValidation) {
                                    Text(stringResource(R.string.server_insecure_badge), color = MaterialTheme.colorScheme.error)
                                }
                            }
                        },
                        modifier = Modifier.clickable { onSelect(item.id) },
                    )
                }
            }
            if (operationErrorCode != null) {
                item {
                    Text(
                        stringResource(R.string.server_operation_failed),
                        modifier = Modifier.padding(theme.spacing.three),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ServerDetailScreen(
    profile: ServerProfileSnapshot,
    operationInProgress: Boolean,
    operationErrorCode: String?,
    onBack: () -> Unit,
    onEdit: () -> Unit,
    onSwitch: () -> Unit,
    onRemove: () -> Unit,
    onRestoreSystemTrust: () -> Unit,
    modifier: Modifier,
) {
    val theme = WarmPageThemeValues
    var confirmSwitch by remember { mutableStateOf(false) }
    var confirmRemove by remember { mutableStateOf(false) }
    var confirmRestoreTrust by remember { mutableStateOf(false) }
    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text(profile.displayName) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.navigate_back))
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(theme.spacing.three),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
        ) {
            Text(profile.baseUrl, style = theme.typography.headline)
            Text(
                stringResource(if (profile.isActive) R.string.server_status_active else R.string.server_status_inactive),
                color = if (profile.isActive) theme.colors.brandAccent else theme.colors.textSecondary,
            )
            Text(
                stringResource(
                    if (profile.tlsMode == TlsMode.SystemTrust) R.string.server_tls_system_status
                    else R.string.server_tls_insecure_status,
                ),
                color = if (profile.tlsMode == TlsMode.SystemTrust) theme.colors.textSecondary else MaterialTheme.colorScheme.error,
            )
            if (operationErrorCode != null) {
                Text(stringResource(R.string.server_operation_failed), color = MaterialTheme.colorScheme.error)
            }
            OutlinedButton(onClick = onEdit, enabled = !operationInProgress, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Outlined.Edit, null)
                Text(stringResource(R.string.server_edit_action), modifier = Modifier.padding(start = theme.spacing.one))
            }
            if (!profile.isActive) {
                Button(onClick = { confirmSwitch = true }, enabled = !operationInProgress, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.server_switch_action))
                }
            }
            if (profile.tlsMode == TlsMode.InsecureSkipAllValidation) {
                OutlinedButton(
                    onClick = { confirmRestoreTrust = true },
                    enabled = !operationInProgress,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Outlined.LockReset, null)
                    Text(stringResource(R.string.server_restore_trust_action), modifier = Modifier.padding(start = theme.spacing.one))
                }
            }
            TextButton(onClick = { confirmRemove = true }, enabled = !operationInProgress) {
                Icon(Icons.Outlined.Delete, null, tint = MaterialTheme.colorScheme.error)
                Text(
                    stringResource(R.string.server_remove_action),
                    modifier = Modifier.padding(start = theme.spacing.one),
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }

    if (confirmSwitch) {
        AlertDialog(
            onDismissRequest = { confirmSwitch = false },
            title = { Text(stringResource(R.string.server_switch_confirm_title)) },
            text = { Text(stringResource(R.string.server_switch_confirm_message, profile.displayName)) },
            confirmButton = { TextButton(onClick = { confirmSwitch = false; onSwitch() }) { Text(stringResource(R.string.server_switch_action)) } },
            dismissButton = { TextButton(onClick = { confirmSwitch = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
    if (confirmRemove) {
        AlertDialog(
            onDismissRequest = { confirmRemove = false },
            title = { Text(stringResource(R.string.server_remove_confirm_title)) },
            text = { Text(stringResource(R.string.server_remove_confirm_message, profile.displayName)) },
            confirmButton = {
                TextButton(onClick = { confirmRemove = false; onRemove() }) {
                    Text(stringResource(R.string.server_remove_confirm_action), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { confirmRemove = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
    if (confirmRestoreTrust) {
        AlertDialog(
            onDismissRequest = { confirmRestoreTrust = false },
            title = { Text(stringResource(R.string.server_restore_trust_confirm_title)) },
            text = { Text(stringResource(R.string.server_restore_trust_confirm_message, profile.displayName)) },
            confirmButton = { TextButton(onClick = { confirmRestoreTrust = false; onRestoreSystemTrust() }) { Text(stringResource(R.string.server_restore_trust_action)) } },
            dismissButton = { TextButton(onClick = { confirmRestoreTrust = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}
