package com.ermao.library.ui.components

import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Tab
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ermao.library.ui.theme.WarmPageThemeValues

/**
 * Settings-only text input. Values and the caret are aligned to the trailing edge while
 * labels, supporting text and placeholders retain their normal leading alignment.
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
    textAlign: TextAlign = TextAlign.End,
    keyboardOptions: KeyboardOptions = KeyboardOptions(
        keyboardType = if (password) KeyboardType.Password else KeyboardType.Text,
        imeAction = ImeAction.Next,
    ),
) {
    val theme = WarmPageThemeValues
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        enabled = enabled,
        singleLine = true,
        textStyle = TextStyle(textAlign = textAlign),
        label = { Text(label) },
        supportingText = supportingText?.let { text -> { Text(text) } },
        placeholder = placeholder?.let { text -> { Text(text) } },
        visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = keyboardOptions,
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = theme.colors.textPrimary,
            unfocusedTextColor = theme.colors.textPrimary,
            disabledTextColor = theme.colors.textTertiary,
            focusedContainerColor = theme.colors.surface,
            unfocusedContainerColor = theme.colors.surface,
            disabledContainerColor = theme.colors.canvas,
            cursorColor = theme.colors.actionAccent,
            focusedBorderColor = theme.colors.actionAccent,
            unfocusedBorderColor = theme.colors.divider,
            disabledBorderColor = theme.colors.divider,
            focusedLabelColor = theme.colors.actionAccent,
            unfocusedLabelColor = theme.colors.textSecondary,
            disabledLabelColor = theme.colors.textTertiary,
            focusedPlaceholderColor = theme.colors.textSecondary,
            unfocusedPlaceholderColor = theme.colors.textSecondary,
        ),
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = theme.components.controls.minimumTouchTarget),
    )
}

/** A compact, icon-only save affordance for settings top bars. */
@Composable
fun SettingsSaveAction(
    contentDescription: String,
    enabled: Boolean,
    working: Boolean = false,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    IconButton(
        onClick = onClick,
        enabled = enabled && !working,
        modifier = modifier.semantics {
            this.contentDescription = contentDescription
            role = Role.Button
        },
    ) {
        if (working) {
            CircularProgressIndicator(
                modifier = Modifier.size(20.dp),
                strokeWidth = 2.dp,
            )
        } else {
            Icon(Icons.Filled.Check, contentDescription = null)
        }
    }
}

/** Material tabs shared by settings screens with more than one persisted form. */
@Composable
fun SettingsTabRow(
    selectedIndex: Int,
    tabs: List<String>,
    onSelect: (Int) -> Unit,
    enabled: Boolean = true,
    modifier: Modifier = Modifier,
) {
    PrimaryTabRow(
        selectedTabIndex = selectedIndex,
        modifier = modifier,
        containerColor = WarmPageThemeValues.colors.canvas,
    ) {
        tabs.forEachIndexed { index, label ->
            Tab(
                selected = selectedIndex == index,
                onClick = { if (enabled) onSelect(index) },
                enabled = enabled,
                text = { Text(label) },
            )
        }
    }
}
