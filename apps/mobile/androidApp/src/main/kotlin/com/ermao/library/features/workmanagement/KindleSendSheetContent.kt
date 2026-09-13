package com.ermao.library.features.workmanagement

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.List
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Email
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.graphics.toColorInt
import com.ermao.library.R
import com.ermao.library.design.GeneratedDesignTokens
import com.ermao.library.shared.modules.workmanagement.ManagementSessionState
import com.ermao.library.ui.theme.WarmPageThemeValues

/** Presentation only: selection, readiness and sending remain owned by the shared session. */
@Composable
internal fun KindleSendSheetContent(
    controller: BookManagementController,
    state: ManagementSessionState,
    onClose: () -> Unit,
    onSettings: () -> Unit,
    onQueue: () -> Unit,
    errorText: String?,
) {
    val session = controller.session
    val colors = WarmPageThemeValues.colors
    val spacing = WarmPageThemeValues.spacing
    val shape = RoundedCornerShape(WarmPageThemeValues.radii.control)
    val busy = state.operation != null
    val selectedSurface = Color(GeneratedDesignTokens.App.AccentSofter.toColorInt())
    val warningSurface = Color(GeneratedDesignTokens.App.Warning.toColorInt()).copy(alpha = 0.10f)
    Column(Modifier.fillMaxWidth().fillMaxHeight()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = spacing.half),
            verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onClose, enabled = !busy) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, stringResource(R.string.cancel_action))
            }
            Text(stringResource(R.string.work_control_send_kindle), Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            IconButton(onClick = onClose, enabled = !busy) {
                Icon(Icons.Outlined.Close, stringResource(R.string.cancel_action))
            }
        }
        HorizontalDivider(color = colors.divider)
        Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(spacing.two),
            verticalArrangement = Arrangement.spacedBy(spacing.oneAndHalf)) {
            Text(stringResource(R.string.management_kindle_book_context, state.target?.title.orEmpty()), style = MaterialTheme.typography.bodyMedium,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(stringResource(R.string.management_kindle_hint), style = MaterialTheme.typography.bodySmall, color = colors.textSecondary)
            Surface(shape = shape, color = colors.surfaceRaised, border = BorderStroke(1.dp, colors.divider)) {
                Column(Modifier.fillMaxWidth().padding(spacing.two), verticalArrangement = Arrangement.spacedBy(spacing.half)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(spacing.one), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Outlined.Email, null, Modifier.size(18.dp), tint = colors.textSecondary)
                        Text(stringResource(R.string.management_kindle_recipient), style = MaterialTheme.typography.bodySmall, color = colors.textSecondary)
                    }
                    Text(state.kindleSettings?.recipientEmail?.takeIf { it.isNotBlank() }
                        ?: stringResource(R.string.management_kindle_unconfigured), style = MaterialTheme.typography.bodyMedium)
                }
            }
            if (!busy && state.kindleSettings != null && state.kindleSettings?.ready != true) {
                Surface(shape = shape, color = warningSurface) {
                    Row(Modifier.fillMaxWidth().padding(spacing.oneAndHalf), horizontalArrangement = Arrangement.spacedBy(spacing.one)) {
                        Icon(Icons.Outlined.Info, null, Modifier.size(18.dp), tint = colors.textSecondary)
                        Text(stringResource(R.string.management_kindle_not_ready), style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            if (errorText != null) {
                Text(errorText, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                if (state.kindleSettings == null && !busy) TextButton(onClick = { controller.perform { loadKindle() } }) {
                    Text(stringResource(R.string.retry_action))
                }
            }
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            Text(stringResource(R.string.management_kindle_choose), style = MaterialTheme.typography.titleSmall)
            if (session.kindleOptions().isEmpty()) Text(stringResource(R.string.management_kindle_empty), style = MaterialTheme.typography.bodyMedium, color = colors.textSecondary)
            Column(Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(spacing.oneAndHalf)) {
                session.kindleOptions().forEach { resource ->
                    resource.assets.filter { it.role == "PRIMARY" }.forEach { asset ->
                        val selected = state.selectedAssetId == asset.id
                        Surface(shape = shape, color = if (selected) selectedSurface else colors.surfaceRaised,
                            border = BorderStroke(1.dp, if (selected) colors.actionAccent else colors.divider)) {
                            Row(Modifier.fillMaxWidth().selectable(selected, enabled = !busy, role = Role.RadioButton,
                                onClick = { session.setAsset(asset.id) }).padding(spacing.oneAndHalf),
                                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(spacing.oneAndHalf)) {
                                RadioButton(selected, onClick = null, enabled = !busy)
                                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(spacing.half)) {
                                    Text(resource.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                    Text("${resource.format} · ${asset.size}", style = MaterialTheme.typography.bodySmall, color = colors.textSecondary)
                                }
                            }
                        }
                    }
                }
            }
        }
        HorizontalDivider(color = colors.divider)
        Column(Modifier.fillMaxWidth().background(colors.surfaceRaised).padding(horizontal = spacing.two).padding(top = spacing.oneAndHalf)) {
            Button(onClick = { controller.perform { sendKindle() } }, shape = shape,
                colors = ButtonDefaults.buttonColors(disabledContainerColor = colors.actionAccent.copy(alpha = 0.42f),
                    disabledContentColor = colors.onAction),
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                enabled = !busy && state.kindleSettings?.ready == true && state.selectedAssetId.isNotBlank()) {
                Icon(Icons.AutoMirrored.Outlined.Send, null, Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.width(ButtonDefaults.IconSpacing))
                Text(stringResource(R.string.management_send_kindle))
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                TextButton(onClick = { session.close(); onSettings() }, enabled = !busy) {
                    Icon(Icons.Outlined.Settings, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(spacing.one))
                    Text(stringResource(R.string.management_kindle_settings_short), style = MaterialTheme.typography.bodySmall)
                }
                TextButton(onClick = { session.close(); onQueue() }, enabled = !busy) {
                    Icon(Icons.AutoMirrored.Outlined.List, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(spacing.one))
                    Text(stringResource(R.string.management_kindle_queue), style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
