package com.ermao.library.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBackIos
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.ui.theme.WarmPageThemeValues

/** The two stable layouts used by all mobile settings destinations. */
enum class WarmSettingsScaffoldRole {
    Root,
    Detail,
}

/** Compatibility alias for callers that prefer the page-oriented name. */
typealias WarmSettingsPageRole = WarmSettingsScaffoldRole

/**
 * Shared settings page shell.
 *
 * Root pages delegate to the same root app bar used by the other primary destinations. Detail
 * pages use a fixed small title bar. [tabs] is deliberately hosted inside the detail top bar, so
 * a form's scroll state cannot make a mode switcher disappear.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WarmSettingsScaffold(
    role: WarmSettingsScaffoldRole,
    title: String,
    modifier: Modifier = Modifier,
    navigation: WarmPageNavigationAction? = null,
    onBack: (() -> Unit)? = null,
    navigationContentDescription: String? = null,
    actions: @Composable RowScope.() -> Unit = {},
    tabs: (@Composable () -> Unit)? = null,
    snackbarHost: @Composable () -> Unit = {},
    containerColor: Color? = null,
    topBarContainerColor: Color? = null,
    content: @Composable (PaddingValues) -> Unit,
) {
    val theme = WarmPageThemeValues
    val resolvedContainerColor = containerColor ?: theme.colors.canvas
    val resolvedTopBarColor = topBarContainerColor ?: resolvedContainerColor
    val navigationAction = navigation ?: onBack?.let {
        WarmPageNavigationAction(
            icon = Icons.AutoMirrored.Rounded.ArrowBackIos,
            label = navigationContentDescription ?: stringResource(R.string.navigate_back),
            onClick = it,
        )
    }

    if (role == WarmSettingsScaffoldRole.Root) {
        WarmPageScaffold(
            role = WarmPageTopBarRole.Root,
            title = title,
            modifier = modifier,
            navigation = navigationAction,
            actionContent = actions,
            snackbarHost = snackbarHost,
            containerColor = resolvedContainerColor,
            topBarContainerColor = resolvedTopBarColor,
        ) { contentPadding ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .testTag("settings-page"),
            ) {
                content(contentPadding)
            }
        }
        return
    }

    val topBarColors = TopAppBarDefaults.topAppBarColors(
        containerColor = resolvedTopBarColor,
        scrolledContainerColor = theme.colors.surface,
        navigationIconContentColor = theme.colors.textPrimary,
        titleContentColor = theme.colors.textPrimary,
        actionIconContentColor = theme.colors.textPrimary,
    )

    Scaffold(
        modifier = modifier,
        containerColor = resolvedContainerColor,
        contentColor = theme.colors.textPrimary,
        topBar = {
            Column(modifier = Modifier.fillMaxWidth()) {
                TopAppBar(
                    title = {
                        Text(
                            text = title,
                            style = theme.typography.sectionTitle,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.testTag("settings-page-title"),
                        )
                    },
                    navigationIcon = {
                        navigationAction?.let { action ->
                            IconButton(
                                onClick = action.onClick,
                                modifier = Modifier.testTag("settings-back"),
                            ) {
                                Icon(
                                    imageVector = action.icon,
                                    contentDescription = action.label,
                                )
                            }
                        }
                    },
                    actions = actions,
                    colors = topBarColors,
                )
                tabs?.let { tabContent ->
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        color = resolvedTopBarColor,
                        contentColor = theme.colors.textPrimary,
                        tonalElevation = 0.dp,
                    ) {
                        tabContent()
                    }
                }
            }
        },
        snackbarHost = snackbarHost,
    ) { contentPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .testTag("settings-page"),
        ) {
            content(contentPadding)
        }
    }
}

/** A section label and its flat group of rows. */
@Composable
fun WarmSettingsSection(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier.fillMaxWidth(),
    ) {
        Text(
            text = title,
            style = theme.typography.label,
            color = theme.colors.textSecondary,
            modifier = Modifier
                .fillMaxWidth()
                .padding(
                    start = theme.components.settings.horizontalInset,
                    end = theme.components.settings.horizontalInset,
                    top = theme.components.settings.sectionSpacing,
                    bottom = theme.components.settings.sectionHeaderBottomSpacing,
                )
                .semantics { heading() },
        )
        content()
    }
}

/** A row that navigates to another settings destination. */
@Composable
fun WarmSettingsNavigationRow(
    title: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    summary: String? = null,
    status: String? = null,
    icon: ImageVector? = null,
    enabled: Boolean = true,
) {
    val theme = WarmPageThemeValues
    WarmSettingsRowContainer(
        modifier = modifier
            .heightIn(min = theme.components.settings.rowMinimumHeight)
            .semantics(mergeDescendants = true) {},
        onClick = onClick,
        enabled = enabled,
        role = Role.Button,
    ) {
        icon?.let { navigationIcon ->
            Box(
                modifier = Modifier.size(theme.components.settings.iconSlotSize),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = navigationIcon,
                    contentDescription = null,
                    tint = if (enabled) theme.colors.textPrimary else theme.colors.textTertiary,
                    modifier = Modifier.size(theme.components.settings.iconSize),
                )
            }
            Spacer(Modifier.width(theme.components.settings.iconTitleSpacing))
        }
        WarmSettingsRowText(title, summary, Modifier.weight(1f))
        status?.takeIf(String::isNotBlank)?.let {
            Text(
                text = it,
                style = theme.typography.label,
                color = if (enabled) theme.colors.textSecondary else theme.colors.textTertiary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                textAlign = TextAlign.End,
                modifier = Modifier
                    .weight(0.45f)
                    .padding(start = theme.spacing.two),
            )
        }
        Icon(
            imageVector = Icons.AutoMirrored.Rounded.KeyboardArrowRight,
            contentDescription = null,
            tint = if (enabled) theme.colors.textSecondary else theme.colors.textTertiary,
            modifier = Modifier.size(theme.components.settings.trailingSlotWidth),
        )
    }
}

/** A non-editable value row, optionally tappable to choose a value. */
@Composable
fun WarmSettingsValueRow(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    supporting: String? = null,
    icon: ImageVector? = null,
    enabled: Boolean = true,
    onClick: (() -> Unit)? = null,
) {
    val theme = WarmPageThemeValues
    WarmSettingsRowContainer(
        modifier = modifier.heightIn(min = theme.components.settings.rowMinimumHeight),
        onClick = onClick,
        enabled = enabled,
        role = Role.Button,
    ) {
        icon?.let { leadingIcon ->
            Box(
                modifier = Modifier.size(theme.components.settings.iconSlotSize),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = leadingIcon,
                    contentDescription = null,
                    tint = if (enabled) theme.colors.textPrimary else theme.colors.textTertiary,
                    modifier = Modifier.size(theme.components.settings.iconSize),
                )
            }
            Spacer(Modifier.width(theme.components.settings.iconTitleSpacing))
        }
        WarmSettingsRowText(label, supporting, Modifier.weight(1f))
        Text(
            text = value,
            style = theme.typography.label,
            color = if (enabled) theme.colors.textSecondary else theme.colors.textTertiary,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.End,
            modifier = Modifier
                .weight(0.45f)
                .padding(start = theme.spacing.two),
        )
    }
}

/** A full-row switch with one owner for the interaction semantics. */
@Composable
fun WarmSettingsSwitchRow(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    supporting: String? = null,
    enabled: Boolean = true,
) {
    val theme = WarmPageThemeValues
    WarmSettingsRowContainer(
        modifier = modifier.heightIn(min = theme.components.settings.rowMinimumHeight),
        onClick = { onCheckedChange(!checked) },
        onToggle = onCheckedChange,
        enabled = enabled,
        role = Role.Switch,
        selectionState = checked,
    ) {
        WarmSettingsRowText(label, supporting, Modifier.weight(1f))
        Switch(
            checked = checked,
            onCheckedChange = null,
            enabled = enabled,
            modifier = Modifier
                .sizeIn(minWidth = theme.components.controls.minimumTouchTarget)
                .clearAndSetSemantics {},
        )
    }
}

/** A full-row radio choice with one owner for the interaction semantics. */
@Composable
fun WarmSettingsRadioRow(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    supporting: String? = null,
    enabled: Boolean = true,
) {
    val theme = WarmPageThemeValues
    WarmSettingsRowContainer(
        modifier = modifier.heightIn(min = theme.components.settings.rowMinimumHeight),
        onClick = onClick,
        enabled = enabled,
        role = Role.RadioButton,
        selectionState = selected,
    ) {
        WarmSettingsRowText(label, supporting, Modifier.weight(1f))
        RadioButton(
            selected = selected,
            onClick = null,
            enabled = enabled,
            modifier = Modifier
                .size(theme.components.controls.minimumTouchTarget)
                .clearAndSetSemantics {},
        )
    }
}

@Immutable
data class WarmSettingsFilterOption<T>(
    val value: T,
    val label: String,
    val enabled: Boolean = true,
)

@Immutable
data class WarmSettingsChoice<T>(
    val id: String,
    val value: T,
    val label: String,
    val supporting: String? = null,
    val enabled: Boolean = true,
)

/** Horizontally scrollable filter controls with a consistent 48dp touch target. */
@Composable
fun <T> WarmSettingsFilterBar(
    options: List<WarmSettingsFilterOption<T>>,
    selected: T,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val theme = WarmPageThemeValues
    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = theme.components.settings.horizontalInset)
            .testTag("settings-filter-bar"),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.one),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        options.forEach { option ->
            FilterChip(
                selected = selected == option.value,
                onClick = { onSelect(option.value) },
                enabled = enabled && option.enabled,
                label = {
                    Text(
                        text = option.label,
                        style = theme.typography.label,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                modifier = Modifier.heightIn(min = theme.components.controls.minimumTouchTarget),
            )
        }
    }
}

/** Single-choice sheet for long labels or enumerations that do not fit a compact segmented row. */
@Composable
fun <T> WarmSettingsChoiceSheet(
    title: String,
    options: List<WarmSettingsChoice<T>>,
    selected: T,
    onSelect: (T) -> Unit,
    onDismissRequest: () -> Unit,
    modifier: Modifier = Modifier,
) {
    WarmPageModalBottomSheet(
        onDismissRequest = onDismissRequest,
        modifier = modifier.testTag("settings-choice-sheet"),
    ) {
        Text(
            text = title,
            style = WarmPageThemeValues.typography.sectionTitle,
            color = WarmPageThemeValues.colors.textPrimary,
            modifier = Modifier
                .fillMaxWidth()
                .padding(WarmPageThemeValues.components.settings.horizontalInset)
                .semantics { heading() },
        )
        options.forEach { option ->
            WarmSettingsRadioRow(
                label = option.label,
                supporting = option.supporting,
                selected = option.value == selected,
                enabled = option.enabled,
                onClick = {
                    onSelect(option.value)
                    onDismissRequest()
                },
                modifier = Modifier.testTag("settings-choice-${option.id}"),
            )
        }
        Spacer(Modifier.size(WarmPageThemeValues.spacing.two))
    }
}

enum class WarmSettingsContentStateKind {
    Loading,
    Empty,
    Error,
}

/** Standard full-width loading, empty, and error state for settings collections. */
@Composable
fun WarmSettingsContentState(
    kind: WarmSettingsContentStateKind,
    title: String,
    modifier: Modifier = Modifier,
    message: String? = null,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = theme.components.settings.horizontalInset, vertical = theme.spacing.six)
            .testTag(
                when (kind) {
                    WarmSettingsContentStateKind.Loading -> "settings-loading"
                    WarmSettingsContentStateKind.Empty -> "settings-empty"
                    WarmSettingsContentStateKind.Error -> "settings-error"
                },
            ),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
    ) {
        if (kind == WarmSettingsContentStateKind.Loading) {
            CircularProgressIndicator(
                modifier = Modifier.size(theme.components.controls.loadingIndicatorSize),
                color = theme.colors.actionAccent,
                strokeWidth = 2.dp,
            )
        }
        Text(
            text = title,
            style = theme.typography.body,
            color = theme.colors.textPrimary,
            textAlign = TextAlign.Center,
        )
        message?.takeIf(String::isNotBlank)?.let {
            Text(
                text = it,
                style = theme.typography.callout,
                color = theme.colors.textSecondary,
                textAlign = TextAlign.Center,
            )
        }
        if (actionLabel != null && onAction != null) {
            TextButton(
                onClick = onAction,
                modifier = Modifier.heightIn(min = theme.components.controls.minimumTouchTarget),
            ) {
                Text(actionLabel, style = theme.typography.button)
            }
        }
    }
}

/** Standard empty state for queues, logs, downloads, and other settings collections. */
@Composable
fun WarmSettingsEmptyState(
    title: String,
    modifier: Modifier = Modifier,
    message: String? = null,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    WarmSettingsContentState(
        kind = WarmSettingsContentStateKind.Empty,
        title = title,
        message = message,
        actionLabel = actionLabel,
        onAction = onAction,
        modifier = modifier,
    )
}

/** Explicit destructive action placed at the end of a settings page. */
@Composable
fun WarmSettingsDangerAction(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    supporting: String? = null,
    enabled: Boolean = true,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = Modifier.fillMaxWidth(),
    ) {
        HorizontalDivider(color = theme.colors.divider)
        WarmSettingsRowContainer(
            modifier = modifier
                .fillMaxWidth()
                .heightIn(min = theme.components.settings.bottomActionHeight),
            onClick = onClick,
            enabled = enabled,
            role = Role.Button,
        ) {
            WarmSettingsRowText(
                title = label,
                summary = supporting,
                modifier = Modifier.weight(1f),
                titleColor = if (enabled) androidx.compose.material3.MaterialTheme.colorScheme.error else theme.colors.textTertiary,
            )
        }
    }
}

/** Compact identity header used by profile and user editors. */
@Composable
fun WarmSettingsIdentityHeader(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    avatar: (@Composable () -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    val theme = WarmPageThemeValues
    val fontScale = LocalDensity.current.fontScale
    BoxWithConstraints(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = theme.components.settings.identityMinimumHeight)
            .padding(
                horizontal = theme.components.settings.horizontalInset,
                vertical = theme.components.settings.verticalInset,
            ),
    ) {
        if (fontScale > 1.3f || maxWidth < 360.dp) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(theme.spacing.one),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
                ) {
                    avatar?.invoke()
                    WarmSettingsRowText(title, subtitle, Modifier.weight(1f))
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                    content = actions,
                )
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
            ) {
                avatar?.invoke()
                WarmSettingsRowText(title, subtitle, Modifier.weight(1f))
                actions()
            }
        }
    }
}

/** Simple loading/error-compatible inline status primitive for settings pages. */
@Composable
fun WarmSettingsInlineMessage(
    message: String,
    modifier: Modifier = Modifier,
    color: Color? = null,
) {
    val resolvedColor = color ?: WarmPageThemeValues.colors.textSecondary
    Text(
        text = message,
        style = WarmPageThemeValues.typography.callout,
        color = resolvedColor,
        modifier = modifier
            .fillMaxWidth()
            .padding(
                horizontal = WarmPageThemeValues.components.settings.horizontalInset,
                vertical = WarmPageThemeValues.components.settings.verticalInset,
            ),
    )
}

/** Divider aligned with either the page inset or the title after a navigation icon slot. */
@Composable
fun WarmSettingsDivider(
    modifier: Modifier = Modifier,
    afterIcon: Boolean = false,
) {
    val theme = WarmPageThemeValues
    val start = theme.components.settings.horizontalInset + if (afterIcon) {
        theme.components.settings.iconSlotSize + theme.components.settings.iconTitleSpacing
    } else {
        0.dp
    }
    HorizontalDivider(
        modifier = modifier.padding(start = start),
        color = theme.colors.divider,
        thickness = theme.components.dividerThickness,
    )
}

@Composable
private fun WarmSettingsRowText(
    title: String,
    summary: String?,
    modifier: Modifier,
    titleColor: Color? = null,
) {
    val theme = WarmPageThemeValues
    val resolvedTitleColor = titleColor ?: theme.colors.textPrimary
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = title,
            style = theme.typography.body,
            color = resolvedTitleColor,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        summary?.takeIf(String::isNotBlank)?.let {
            Text(
                text = it,
                style = theme.typography.callout,
                color = theme.colors.textSecondary,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun WarmSettingsRowContainer(
    modifier: Modifier,
    onClick: (() -> Unit)?,
    onToggle: ((Boolean) -> Unit)? = null,
    enabled: Boolean,
    role: Role,
    selectionState: Boolean? = null,
    content: @Composable RowScope.() -> Unit,
) {
    val theme = WarmPageThemeValues
    val interactionModifier = if (onClick == null) {
        Modifier
    } else if (onToggle != null && selectionState != null && role == Role.Switch) {
        Modifier.toggleable(
            value = selectionState,
            enabled = enabled,
            role = role,
            onValueChange = onToggle,
        )
    } else if (selectionState != null && role == Role.RadioButton) {
        Modifier.selectable(
            selected = selectionState,
            enabled = enabled,
            role = role,
            onClick = checkNotNull(onClick),
        )
    } else {
        Modifier.clickable(
            enabled = enabled,
            role = role,
            onClick = onClick,
        )
    }
    Row(
        modifier = modifier
            .fillMaxWidth()
            .then(interactionModifier)
            .padding(
                horizontal = theme.components.settings.horizontalInset,
                vertical = theme.components.settings.verticalInset,
            ),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Start,
        content = content,
    )
}
