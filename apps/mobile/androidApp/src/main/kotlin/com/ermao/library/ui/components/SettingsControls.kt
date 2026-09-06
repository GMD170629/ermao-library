package com.ermao.library.ui.components

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.res.stringResource
import com.ermao.library.R
import com.ermao.library.ui.theme.WarmPageThemeValues

/**
 * Settings text input with a stable left-to-right editing affordance.
 *
 * The optional [textAlign] argument remains for source compatibility with older callers. New
 * settings pages, including numeric fields, use the default [TextAlign.Start].
 */
@Composable
fun SettingsTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    supportingText: String? = null,
    placeholder: String? = null,
    enabled: Boolean = true,
    password: Boolean = false,
    textAlign: TextAlign = TextAlign.Start,
    keyboardOptions: KeyboardOptions = KeyboardOptions(
        keyboardType = if (password) KeyboardType.Password else KeyboardType.Text,
        imeAction = ImeAction.Next,
    ),
    showPasswordContentDescription: String? = null,
    hidePasswordContentDescription: String? = null,
) {
    val theme = WarmPageThemeValues
    var passwordVisible by rememberSaveable(label) { mutableStateOf(false) }
    val showPasswordLabel = showPasswordContentDescription ?: stringResource(R.string.login_show_password)
    val hidePasswordLabel = hidePasswordContentDescription ?: stringResource(R.string.login_hide_password)
    val effectiveTransformation = when {
        !password || passwordVisible -> VisualTransformation.None
        else -> PasswordVisualTransformation()
    }
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        enabled = enabled,
        singleLine = true,
        textStyle = theme.typography.body.copy(textAlign = textAlign),
        label = { Text(label, style = theme.typography.label) },
        supportingText = supportingText?.let { text ->
            { Text(text, style = theme.typography.caption) }
        },
        placeholder = placeholder?.let { text ->
            { Text(text, style = theme.typography.callout) }
        },
        trailingIcon = if (password) {
            {
                IconButton(
                    onClick = { passwordVisible = !passwordVisible },
                    enabled = enabled,
                    modifier = Modifier.size(theme.components.controls.minimumTouchTarget),
                ) {
                    Icon(
                        imageVector = if (passwordVisible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                        contentDescription = if (passwordVisible) {
                            hidePasswordLabel
                        } else {
                            showPasswordLabel
                        },
                        modifier = Modifier.size(theme.components.controls.iconSize),
                    )
                }
            }
        } else {
            null
        },
        visualTransformation = effectiveTransformation,
        keyboardOptions = keyboardOptions,
        shape = WarmPageTextFieldDefaults.shape,
        colors = WarmPageTextFieldDefaults.colors(),
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = theme.components.controls.minimumTouchTarget),
    )
}

/**
 * Explicit settings save action.
 *
 * Older callers provide [contentDescription] only, so it remains the default visible label as
 * well as the accessibility description. The text affordance makes the action discoverable in
 * a top bar and remains compatible with existing call sites.
 */
@Composable
fun SettingsSaveAction(
    contentDescription: String,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    working: Boolean = false,
    label: String = contentDescription,
) {
    val theme = WarmPageThemeValues
    val accessibilityModifier = if (working || label != contentDescription) {
        Modifier.semantics {
            this.contentDescription = contentDescription
            role = Role.Button
        }
    } else {
        Modifier
    }
    TextButton(
        onClick = onClick,
        enabled = enabled && !working,
        modifier = modifier
            .heightIn(min = theme.components.controls.minimumTouchTarget)
            .then(accessibilityModifier)
            .testTag("settings-save"),
    ) {
        if (working) {
            CircularProgressIndicator(
                modifier = Modifier.size(theme.components.controls.loadingIndicatorSize),
                strokeWidth = 2.dp,
            )
        } else {
            Text(label, style = theme.typography.button)
        }
    }
}

/** Material tabs shared by settings screens with a small, fixed set of modes. */
@Composable
fun SettingsTabRow(
    selectedIndex: Int,
    tabs: List<String>,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    enabledForTab: (Int) -> Boolean = { true },
) {
    val theme = WarmPageThemeValues
    if (tabs.isEmpty()) return
    val safeSelectedIndex = selectedIndex.coerceIn(0, tabs.lastIndex)
    PrimaryTabRow(
        selectedTabIndex = safeSelectedIndex,
        modifier = modifier.fillMaxWidth().testTag("settings-tabs"),
        containerColor = theme.colors.canvas,
        contentColor = theme.colors.textPrimary,
        divider = {
            androidx.compose.material3.HorizontalDivider(color = theme.colors.divider)
        },
    ) {
        tabs.forEachIndexed { index, label ->
            val tabEnabled = enabled && enabledForTab(index)
            Tab(
                selected = safeSelectedIndex == index,
                onClick = { if (tabEnabled) onSelect(index) },
                enabled = tabEnabled,
                selectedContentColor = theme.colors.brandAccent,
                unselectedContentColor = theme.colors.textSecondary,
                modifier = Modifier
                    .heightIn(min = theme.components.controls.minimumTouchTarget),
                text = {
                    Text(
                        text = label,
                        style = theme.typography.label,
                        maxLines = 1,
                    )
                },
            )
        }
    }
}
