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
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.layout.widthIn
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
import androidx.compose.ui.platform.testTag
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
    val enabled: Boolean = true,
    val destructive: Boolean = false,
    val testTag: String? = null,
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
            val menuWidth = maxWidth.coerceAtMost(theme.components.menu.maximumWidth)
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
                shape = RoundedCornerShape(theme.radii.task),
                color = theme.colors.surfaceRaised.copy(alpha = 0.90f),
                contentColor = theme.colors.textPrimary,
                border = BorderStroke(1.dp, theme.colors.divider.copy(alpha = 0.72f)),
                shadowElevation = 14.dp,
            ) {
                Column {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = theme.components.menu.itemHorizontalPadding, vertical = theme.spacing.oneAndHalf),
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
            .heightIn(min = theme.components.menu.itemMinimumHeight)
            .clickable(enabled = action.enabled) { onSelect(action.value) }
            .padding(horizontal = theme.components.menu.itemHorizontalPadding, vertical = theme.spacing.half),
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
            modifier = Modifier.size(theme.components.menu.iconSlotSize),
        )
    }
}

@Composable
fun <T> WarmPageActionMenu(
    expanded: Boolean,
    actions: List<WarmPageMenuAction<T>>,
    onSelect: (T) -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    title: String? = null,
) {
    WarmPagePopup(expanded, onDismiss, modifier, title) {
        val hasLeadingSlot = actions.any { it.leadingIcon != null }
        actions.forEach { action ->
            WarmPageMenuItem(
                label = action.label,
                onClick = { onSelect(action.value) },
                leadingIcon = action.leadingIcon,
                hasLeadingSlot = hasLeadingSlot,
                enabled = action.enabled,
                destructive = action.destructive,
                modifier = action.testTag?.let { Modifier.testTag(it) } ?: Modifier,
            )
        }
    }
}

@Composable
fun <T> WarmPageSingleChoiceMenu(
    expanded: Boolean,
    options: List<WarmPageMenuOption<T>>,
    selected: T,
    onSelect: (T) -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    title: String? = null,
    dismissLabel: String? = null,
) {
    val theme = WarmPageThemeValues
    WarmPagePopup(expanded, onDismiss, modifier, title) {
        val hasLeadingSlot = options.any { it.leadingIcon != null }
        options.forEach { option ->
            WarmPageMenuItem(
                label = option.label,
                onClick = { onSelect(option.value) },
                leadingIcon = option.leadingIcon,
                hasLeadingSlot = hasLeadingSlot,
                selected = option.value == selected,
            )
        }
        dismissLabel?.let { label ->
            HorizontalDivider(
                thickness = theme.components.dividerThickness,
                color = theme.colors.divider,
            )
            WarmPageMenuItem(label = label, onClick = onDismiss)
        }
    }
}

/** Native popup shell and branded content have one owner for both action and choice menus. */
@Composable
fun WarmPagePopup(
    expanded: Boolean,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    title: String? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val theme = WarmPageThemeValues
    DropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismiss,
        modifier = modifier.widthIn(max = theme.components.menu.maximumWidth),
        shape = RoundedCornerShape(theme.radii.task),
        containerColor = theme.colors.surfaceRaised,
        tonalElevation = theme.spacing.none,
    ) {
        title?.let { label ->
            Text(
                text = label,
                style = theme.typography.caption,
                color = theme.colors.textSecondary,
                modifier = Modifier.padding(
                    horizontal = theme.components.menu.titleHorizontalPadding,
                    vertical = theme.components.menu.titleVerticalPadding,
                ),
            )
        }
        content()
    }
}

@Composable
fun WarmPageMenuItem(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    leadingIcon: ImageVector? = null,
    hasLeadingSlot: Boolean = false,
    selected: Boolean? = null,
    enabled: Boolean = true,
    destructive: Boolean = false,
) {
    val theme = WarmPageThemeValues
    val foreground = when {
        destructive -> androidx.compose.material3.MaterialTheme.colorScheme.error
        selected == true -> theme.colors.brandAccent
        else -> theme.colors.textPrimary
    }
    val selectionModifier = if (selected == null) Modifier else Modifier.semantics {
        this.selected = selected
        role = Role.RadioButton
    }
    DropdownMenuItem(
        text = {
            Text(label, style = theme.typography.body, modifier = Modifier.fillMaxWidth())
        },
        onClick = onClick,
        enabled = enabled,
        leadingIcon = if (hasLeadingSlot) {
            {
                Box(Modifier.size(theme.components.menu.iconSlotSize), contentAlignment = Alignment.Center) {
                    leadingIcon?.let { Icon(it, contentDescription = null, modifier = Modifier.fillMaxSize()) }
                }
            }
        } else null,
        trailingIcon = if (selected != null) {
            {
                Box(Modifier.size(theme.components.menu.iconSlotSize), contentAlignment = Alignment.Center) {
                    if (selected) {
                        Icon(Icons.Filled.Check, contentDescription = null, modifier = Modifier.fillMaxSize())
                    }
                }
            }
        } else null,
        colors = MenuDefaults.itemColors(
            textColor = foreground,
            leadingIconColor = if (destructive || selected == true) foreground else theme.colors.textSecondary,
            trailingIconColor = theme.colors.brandAccent,
            disabledTextColor = theme.colors.textTertiary,
            disabledLeadingIconColor = theme.colors.textTertiary,
            disabledTrailingIconColor = theme.colors.textTertiary,
        ),
        contentPadding = PaddingValues(horizontal = theme.components.menu.itemHorizontalPadding),
        modifier = modifier
            .heightIn(min = theme.components.menu.itemMinimumHeight)
            .then(selectionModifier),
    )
}
