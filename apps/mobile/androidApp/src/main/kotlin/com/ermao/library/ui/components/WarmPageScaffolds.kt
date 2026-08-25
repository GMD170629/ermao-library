package com.ermao.library.ui.components

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import com.ermao.library.ui.theme.WarmPageThemeValues

enum class WarmPageTopBarRole {
    Root,
    Detail,
}

data class WarmPageNavigationAction(
    val icon: ImageVector,
    val label: String,
    val onClick: () -> Unit,
)

data class WarmPageTopBarAction(
    val icon: ImageVector,
    val label: String,
    val enabled: Boolean = true,
    val onClick: () -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WarmPageScaffold(
    role: WarmPageTopBarRole,
    title: String,
    modifier: Modifier = Modifier,
    navigation: WarmPageNavigationAction? = null,
    actions: List<WarmPageTopBarAction> = emptyList(),
    actionContent: @Composable RowScope.() -> Unit = {},
    snackbarHost: @Composable () -> Unit = {},
    containerColor: Color? = null,
    topBarContainerColor: Color? = null,
    content: @Composable (PaddingValues) -> Unit,
) {
    val theme = WarmPageThemeValues
    val resolvedContainerColor = containerColor ?: theme.colors.canvas
    val resolvedTopBarContainerColor = topBarContainerColor ?: theme.colors.canvas
    Scaffold(
        modifier = modifier,
        containerColor = resolvedContainerColor,
        contentColor = theme.colors.textPrimary,
        topBar = {
            val titleContent: @Composable () -> Unit = {
                Text(
                    text = title,
                    style = if (role == WarmPageTopBarRole.Root) {
                        theme.typography.display
                    } else {
                        theme.typography.headline
                    },
                    color = theme.colors.textPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            val navigationContent: @Composable () -> Unit = {
                navigation?.let { action ->
                    WarmPageToolbarIcon(action.icon, action.label, true, action.onClick)
                }
            }
            val actionsContent: @Composable RowScope.() -> Unit = {
                WarmPageTopBarActions(actions)
                actionContent()
            }
            val topBarModifier = Modifier.heightIn(
                min = if (role == WarmPageTopBarRole.Root) {
                    theme.components.topBar.rootHeight
                } else {
                    theme.components.topBar.detailHeight
                },
            )
            val topBarColors = TopAppBarDefaults.topAppBarColors(
                containerColor = resolvedTopBarContainerColor,
                scrolledContainerColor = theme.colors.surface,
                navigationIconContentColor = theme.colors.textPrimary,
                titleContentColor = theme.colors.textPrimary,
                actionIconContentColor = theme.colors.textPrimary,
            )
            if (role == WarmPageTopBarRole.Detail) {
                CenterAlignedTopAppBar(
                    title = titleContent,
                    modifier = topBarModifier,
                    navigationIcon = navigationContent,
                    actions = actionsContent,
                    colors = topBarColors,
                )
            } else {
                TopAppBar(
                    title = titleContent,
                    modifier = topBarModifier,
                    navigationIcon = navigationContent,
                    actions = actionsContent,
                    colors = topBarColors,
                )
            }
        },
        snackbarHost = snackbarHost,
        content = content,
    )
}

@Composable
private fun RowScope.WarmPageTopBarActions(actions: List<WarmPageTopBarAction>) {
    actions.forEach { action ->
        WarmPageToolbarIcon(action.icon, action.label, action.enabled, action.onClick)
    }
}

@Composable
private fun WarmPageToolbarIcon(
    icon: ImageVector,
    label: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val theme = WarmPageThemeValues
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.size(theme.components.controls.minimumTouchTarget),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = label,
            modifier = Modifier.size(theme.components.controls.toolbarIconSize),
        )
    }
}
