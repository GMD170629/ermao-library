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

/** One visual owner for search and form fields; callers retain their own input behavior. */
internal object WarmPageTextFieldDefaults {
    val shape: RoundedCornerShape
        @Composable get() = RoundedCornerShape(WarmPageThemeValues.radii.control)

    @Composable
    fun colors() = with(WarmPageThemeValues.colors) {
        OutlinedTextFieldDefaults.colors(
            focusedTextColor = textPrimary,
            unfocusedTextColor = textPrimary,
            disabledTextColor = textTertiary,
            focusedContainerColor = surface,
            unfocusedContainerColor = surface,
            disabledContainerColor = surface,
            cursorColor = actionAccent,
            focusedBorderColor = actionAccent,
            unfocusedBorderColor = divider,
            disabledBorderColor = divider,
            focusedLabelColor = actionAccent,
            unfocusedLabelColor = textSecondary,
            disabledLabelColor = textTertiary,
            focusedLeadingIconColor = textSecondary,
            unfocusedLeadingIconColor = textSecondary,
            disabledLeadingIconColor = textTertiary,
            focusedTrailingIconColor = textSecondary,
            unfocusedTrailingIconColor = textSecondary,
            disabledTrailingIconColor = textTertiary,
            focusedPlaceholderColor = textSecondary,
            unfocusedPlaceholderColor = textSecondary,
            disabledPlaceholderColor = textTertiary,
        )
    }
}

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
        textStyle = theme.typography.body,
        placeholder = {
            Text(
                text = placeholder,
                style = theme.typography.callout,
            )
        },
        leadingIcon = {
            Icon(
                imageVector = Icons.Outlined.Search,
                contentDescription = null,
                modifier = Modifier.size(theme.components.controls.iconSize),
            )
        },
        trailingIcon = if (value.isNotEmpty()) {
            {
                IconButton(onClick = onClear, enabled = enabled) {
                    Icon(
                        imageVector = Icons.Filled.Close,
                        contentDescription = clearLabel,
                        modifier = Modifier.size(theme.components.controls.iconSize),
                    )
                }
            }
        } else {
            null
        },
        shape = WarmPageTextFieldDefaults.shape,
        colors = WarmPageTextFieldDefaults.colors(),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = theme.components.controls.searchMinimumHeight),
    )
}
