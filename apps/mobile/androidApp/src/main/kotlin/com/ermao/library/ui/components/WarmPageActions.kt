package com.ermao.library.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import com.ermao.library.ui.theme.WarmPageThemeValues

@Composable
fun WarmPagePrimaryAction(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    loading: Boolean = false,
    leadingIcon: ImageVector? = null,
    trailingIcon: ImageVector? = null,
) {
    val theme = WarmPageThemeValues
    val horizontalContentPadding = warmPageActionHorizontalPadding(
        hasIcon = leadingIcon != null || trailingIcon != null,
        regularPadding = theme.spacing.three,
        compactPadding = theme.spacing.one,
    )
    Button(
        onClick = onClick,
        enabled = enabled && !loading,
        shape = RoundedCornerShape(theme.radii.control),
        colors = ButtonDefaults.buttonColors(
            containerColor = theme.colors.actionAccent,
            contentColor = theme.colors.onAction,
            disabledContainerColor = theme.colors.divider,
            disabledContentColor = theme.colors.textTertiary,
        ),
        contentPadding = PaddingValues(
            horizontal = horizontalContentPadding,
            vertical = theme.spacing.one,
        ),
        modifier = modifier
            .heightIn(min = theme.components.controls.actionMinimumHeight)
            .loadingDescription(loading, label),
    ) {
        WarmPageActionContent(label, loading, theme.colors.onAction, leadingIcon, trailingIcon)
    }
}

@Composable
fun WarmPageSecondaryAction(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    loading: Boolean = false,
    leadingIcon: ImageVector? = null,
    trailingIcon: ImageVector? = null,
) {
    val theme = WarmPageThemeValues
    val horizontalContentPadding = warmPageActionHorizontalPadding(
        hasIcon = leadingIcon != null || trailingIcon != null,
        regularPadding = theme.spacing.three,
        compactPadding = theme.spacing.one,
    )
    OutlinedButton(
        onClick = onClick,
        enabled = enabled && !loading,
        shape = RoundedCornerShape(theme.radii.control),
        border = null,
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = theme.colors.accentSoft,
            contentColor = theme.colors.actionAccent,
            disabledContentColor = theme.colors.textTertiary,
        ),
        contentPadding = PaddingValues(
            horizontal = horizontalContentPadding,
            vertical = theme.spacing.one,
        ),
        modifier = modifier
            .heightIn(min = theme.components.controls.actionMinimumHeight)
            .loadingDescription(loading, label),
    ) {
        WarmPageActionContent(label, loading, theme.colors.actionAccent, leadingIcon, trailingIcon)
    }
}

@Composable
fun WarmPageTextAction(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    leadingIcon: ImageVector? = null,
) {
    val theme = WarmPageThemeValues
    TextButton(
        onClick = onClick,
        enabled = enabled,
        colors = ButtonDefaults.textButtonColors(
            contentColor = theme.colors.actionAccent,
            disabledContentColor = theme.colors.textTertiary,
        ),
        modifier = modifier.heightIn(min = theme.components.controls.minimumTouchTarget),
    ) {
        leadingIcon?.let { icon ->
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier
                    .padding(end = theme.spacing.one)
                    .size(theme.components.controls.iconSize),
            )
        }
        Text(text = label, style = theme.typography.label)
    }
}

@Composable
fun WarmPageIconAction(
    icon: ImageVector,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val theme = WarmPageThemeValues
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.size(theme.components.controls.minimumTouchTarget),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = label,
            tint = if (enabled) theme.colors.textPrimary else theme.colors.textTertiary,
            modifier = Modifier.size(theme.components.controls.iconSize),
        )
    }
}

@Composable
private fun WarmPageActionContent(
    label: String,
    loading: Boolean,
    indicatorColor: Color,
    leadingIcon: ImageVector?,
    trailingIcon: ImageVector?,
) {
    val theme = WarmPageThemeValues
    if (loading) {
        CircularProgressIndicator(
            color = indicatorColor,
            strokeWidth = theme.metrics.coverProgressHeight,
            modifier = Modifier.size(theme.components.controls.loadingIndicatorSize),
        )
    } else {
        Row(
            horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            leadingIcon?.let { icon ->
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    modifier = Modifier
                        .size(theme.components.controls.iconSize)
                        .testTag(WARM_PAGE_ACTION_LEADING_ICON_TEST_TAG),
                )
            }
            Text(
                text = label,
                style = theme.typography.button,
                modifier = Modifier.testTag(WARM_PAGE_ACTION_LABEL_TEST_TAG),
            )
            trailingIcon?.let { icon ->
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    modifier = Modifier
                        .size(theme.components.controls.iconSize)
                        .testTag(WARM_PAGE_ACTION_TRAILING_ICON_TEST_TAG),
                )
            }
        }
    }
}

private fun Modifier.loadingDescription(loading: Boolean, label: String): Modifier =
    if (loading) semantics { contentDescription = label } else this

internal fun warmPageActionHorizontalPadding(
    hasIcon: Boolean,
    regularPadding: Dp,
    compactPadding: Dp,
): Dp = if (hasIcon) compactPadding else regularPadding

internal const val WARM_PAGE_ACTION_LABEL_TEST_TAG = "warm-page-action-label"
internal const val WARM_PAGE_ACTION_LEADING_ICON_TEST_TAG = "warm-page-action-leading-icon"
internal const val WARM_PAGE_ACTION_TRAILING_ICON_TEST_TAG = "warm-page-action-trailing-icon"
