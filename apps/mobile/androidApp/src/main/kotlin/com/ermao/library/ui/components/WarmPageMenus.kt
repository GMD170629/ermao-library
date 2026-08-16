package com.ermao.library.ui.components

import android.os.Build
import android.view.WindowManager
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MenuDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.DialogWindowProvider
import com.ermao.library.ui.theme.WarmPageThemeValues

data class WarmPageMenuOption<T>(
    val value: T,
    val label: String,
    val leadingIcon: ImageVector? = null,
)

data class WarmPageMenuAction<T>(
    val value: T,
    val label: String,
    val leadingIcon: ImageVector? = null,
)

data class WarmPageFloatingMenuAction<T>(
    val value: T,
    val label: String,
    val icon: ImageVector,
    val enabled: Boolean = true,
    val destructive: Boolean = false,
)

@Composable
fun <T> WarmPageFloatingActionMenu(
    actions: List<WarmPageFloatingMenuAction<T>>,
    anchorInWindow: Offset,
    onSelect: (T) -> Unit,
    onDismiss: () -> Unit,
    header: @Composable () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val regularActions = actions.filterNot { it.destructive }
    val destructiveAction = actions.firstOrNull { it.destructive }
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            dismissOnBackPress = true,
            dismissOnClickOutside = true,
            usePlatformDefaultWidth = false,
        ),
    ) {
        val window = (LocalView.current.parent as? DialogWindowProvider)?.window
        SideEffect {
            window?.setDimAmount(0.36f)
            window?.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                window?.let { dialogWindow ->
                    dialogWindow.addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND)
                    dialogWindow.attributes = dialogWindow.attributes.also { attributes ->
                        attributes.blurBehindRadius = 24
                    }
                }
            }
        }
        BoxWithConstraints(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(12.dp)
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                    onClick = onDismiss,
                ),
            contentAlignment = Alignment.TopStart,
        ) {
            val density = LocalDensity.current
            val menuWidth = maxWidth.coerceAtMost(224.dp)
            val menuListHeight = (regularActions.size * 48 + 4).dp
                .coerceAtMost((maxHeight - 132.dp).coerceAtLeast(48.dp))
            val estimatedHeight = 72.dp + menuListHeight +
                (if (destructiveAction == null) 0.dp else 49.dp)
            val anchorX = with(density) { anchorInWindow.x.toDp() } - 12.dp
            val anchorY = with(density) { anchorInWindow.y.toDp() } - 12.dp
            val menuX = if (anchorX + menuWidth <= maxWidth) anchorX else anchorX - menuWidth
            val menuY = if (anchorY + estimatedHeight <= maxHeight) anchorY else anchorY - estimatedHeight
            val clampedX = menuX.coerceIn(0.dp, (maxWidth - menuWidth).coerceAtLeast(0.dp))
            val clampedY = menuY.coerceIn(0.dp, (maxHeight - estimatedHeight).coerceAtLeast(0.dp))
            Surface(
                modifier = modifier
                    .width(menuWidth)
                    .offset {
                        IntOffset(
                            x = with(density) { clampedX.roundToPx() },
                            y = with(density) { clampedY.roundToPx() },
                        )
                    }
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                        onClick = {},
                    ),
                shape = RoundedCornerShape(16.dp),
                color = theme.colors.surfaceRaised.copy(alpha = 0.90f),
                contentColor = theme.colors.textPrimary,
                border = BorderStroke(1.dp, theme.colors.divider.copy(alpha = 0.72f)),
                shadowElevation = 14.dp,
            ) {
                Column {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 12.dp),
                    ) {
                        header()
                    }
                    HorizontalDivider(
                        thickness = theme.components.dividerThickness,
                        color = theme.colors.divider.copy(alpha = 0.72f),
                    )
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().height(menuListHeight),
                        contentPadding = PaddingValues(vertical = theme.spacing.half),
                    ) {
                        items(regularActions, key = { it.value.toString() }) { action ->
                            WarmPageFloatingActionRow(action = action, onSelect = onSelect)
                        }
                    }
                    destructiveAction?.let { action ->
                        HorizontalDivider(
                            thickness = theme.components.dividerThickness,
                            color = theme.colors.divider.copy(alpha = 0.72f),
                        )
                        WarmPageFloatingActionRow(action = action, onSelect = onSelect)
                    }
                }
            }
        }
    }
}

@Composable
private fun <T> WarmPageFloatingActionRow(
    action: WarmPageFloatingMenuAction<T>,
    onSelect: (T) -> Unit,
) {
    val theme = WarmPageThemeValues
    val foreground = when {
        !action.enabled -> theme.colors.textTertiary
        action.destructive -> androidx.compose.material3.MaterialTheme.colorScheme.error
        else -> theme.colors.textPrimary
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 48.dp)
            .clickable(enabled = action.enabled) { onSelect(action.value) }
            .padding(horizontal = 14.dp, vertical = theme.spacing.half),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = action.label,
            style = theme.typography.body,
            color = foreground,
            modifier = Modifier.weight(1f),
        )
        Spacer(Modifier.width(theme.spacing.half))
        Icon(
            imageVector = action.icon,
            contentDescription = null,
            tint = foreground,
            modifier = Modifier.size(20.dp),
        )
    }
}

@Composable
fun <T> WarmPageActionMenu(
    title: String,
    expanded: Boolean,
    actions: List<WarmPageMenuAction<T>>,
    onSelect: (T) -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    DropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismiss,
        modifier = modifier,
        containerColor = theme.colors.surfaceRaised,
        tonalElevation = theme.spacing.none,
    ) {
        Text(
            text = title,
            style = theme.typography.caption,
            color = theme.colors.textSecondary,
            modifier = Modifier.padding(
                horizontal = theme.components.menu.titleHorizontalPadding,
                vertical = theme.components.menu.titleVerticalPadding,
            ),
        )
        actions.forEach { action ->
            DropdownMenuItem(
                text = { Text(text = action.label, style = theme.typography.body) },
                onClick = { onSelect(action.value) },
                leadingIcon = action.leadingIcon?.let { icon ->
                    { Icon(imageVector = icon, contentDescription = null) }
                },
                colors = MenuDefaults.itemColors(
                    textColor = theme.colors.textPrimary,
                    leadingIconColor = theme.colors.textSecondary,
                ),
                modifier = Modifier.heightIn(min = theme.components.menu.itemMinimumHeight),
            )
        }
    }
}

@Composable
fun <T> WarmPageSingleChoiceMenu(
    title: String,
    expanded: Boolean,
    options: List<WarmPageMenuOption<T>>,
    selected: T,
    onSelect: (T) -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    dismissLabel: String? = null,
) {
    val theme = WarmPageThemeValues
    DropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismiss,
        modifier = modifier,
        containerColor = theme.colors.surfaceRaised,
        tonalElevation = theme.spacing.none,
    ) {
        Text(
            text = title,
            style = theme.typography.caption,
            color = theme.colors.textSecondary,
            modifier = Modifier.padding(
                horizontal = theme.components.menu.titleHorizontalPadding,
                vertical = theme.components.menu.titleVerticalPadding,
            ),
        )
        options.forEach { option ->
            val isSelected = option.value == selected
            DropdownMenuItem(
                text = { Text(text = option.label, style = theme.typography.body) },
                onClick = { onSelect(option.value) },
                leadingIcon = option.leadingIcon?.let { icon ->
                    { Icon(imageVector = icon, contentDescription = null) }
                },
                trailingIcon = if (isSelected) {
                    {
                        Icon(
                            imageVector = Icons.Filled.Check,
                            contentDescription = null,
                            tint = theme.colors.brandAccent,
                        )
                    }
                } else {
                    null
                },
                colors = MenuDefaults.itemColors(
                    textColor = theme.colors.textPrimary,
                    leadingIconColor = theme.colors.textSecondary,
                    trailingIconColor = theme.colors.brandAccent,
                    disabledTextColor = theme.colors.textTertiary,
                ),
                modifier = Modifier
                    .heightIn(min = theme.components.menu.itemMinimumHeight)
                    .semantics {
                        this.selected = isSelected
                        role = Role.RadioButton
                    },
            )
        }
        dismissLabel?.let { label ->
            HorizontalDivider(
                thickness = theme.components.dividerThickness,
                color = theme.colors.divider,
            )
            DropdownMenuItem(
                text = { Text(text = label, style = theme.typography.body) },
                onClick = onDismiss,
                colors = MenuDefaults.itemColors(textColor = theme.colors.textPrimary),
                modifier = Modifier.heightIn(min = theme.components.menu.itemMinimumHeight),
            )
        }
    }
}
