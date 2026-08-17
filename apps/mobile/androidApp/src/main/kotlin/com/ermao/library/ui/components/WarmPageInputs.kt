package com.ermao.library.ui.components

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.foundation.text.KeyboardOptions
import com.ermao.library.ui.theme.WarmPageThemeValues

@Composable
fun WarmPageSearchField(
    value: String,
    placeholder: String,
    onValueChange: (String) -> Unit,
    onClear: () -> Unit,
    clearLabel: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val theme = WarmPageThemeValues
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        enabled = enabled,
        singleLine = true,
        textStyle = theme.typography.body.copy(color = theme.colors.textPrimary),
        placeholder = {
            Text(
                text = placeholder,
                style = theme.typography.callout,
                color = theme.colors.textSecondary,
            )
        },
        leadingIcon = {
            Icon(
                imageVector = Icons.Outlined.Search,
                contentDescription = null,
                tint = theme.colors.textSecondary,
                modifier = Modifier.size(theme.components.controls.iconSize),
            )
        },
        trailingIcon = if (value.isNotEmpty()) {
            {
                IconButton(onClick = onClear, enabled = enabled) {
                    Icon(
                        imageVector = Icons.Filled.Close,
                        contentDescription = clearLabel,
                        tint = theme.colors.textSecondary,
                    )
                }
            }
        } else {
            null
        },
        shape = RoundedCornerShape(theme.radii.control),
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
            focusedLeadingIconColor = theme.colors.textSecondary,
            unfocusedLeadingIconColor = theme.colors.textSecondary,
            focusedTrailingIconColor = theme.colors.textSecondary,
            unfocusedTrailingIconColor = theme.colors.textSecondary,
            focusedPlaceholderColor = theme.colors.textSecondary,
            unfocusedPlaceholderColor = theme.colors.textSecondary,
        ),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = theme.components.controls.searchMinimumHeight),
    )
}
