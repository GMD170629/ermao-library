package com.ermao.library.ui.components

import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationDrawerItemDefaults
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteDefaults
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteScaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ermao.library.ui.theme.WarmPageThemeValues

data class WarmPageNavigationItem<T>(
    val id: T,
    @StringRes val labelResource: Int,
    val selectedIcon: ImageVector,
    val unselectedIcon: ImageVector,
    val testTag: String,
)

@Composable
fun <T> WarmPageNavigationSuite(
    items: List<WarmPageNavigationItem<T>>,
    selected: T,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
    bottomAccessory: @Composable () -> Unit = {},
    content: @Composable () -> Unit,
) {
    val theme = WarmPageThemeValues
    val itemColors = NavigationSuiteDefaults.itemColors(
        navigationBarItemColors = NavigationBarItemDefaults.colors(
            selectedIconColor = theme.colors.brandAccent,
            selectedTextColor = theme.colors.brandAccent,
            indicatorColor = Color.Transparent,
            unselectedIconColor = theme.colors.textSecondary,
            unselectedTextColor = theme.colors.textSecondary,
        ),
        navigationRailItemColors = NavigationRailItemDefaults.colors(
            selectedIconColor = theme.colors.brandAccent,
            selectedTextColor = theme.colors.brandAccent,
            indicatorColor = Color.Transparent,
            unselectedIconColor = theme.colors.textSecondary,
            unselectedTextColor = theme.colors.textSecondary,
            disabledIconColor = theme.colors.textTertiary,
            disabledTextColor = theme.colors.textTertiary,
        ),
        navigationDrawerItemColors = NavigationDrawerItemDefaults.colors(
            selectedIconColor = theme.colors.brandAccent,
            selectedTextColor = theme.colors.brandAccent,
            selectedContainerColor = theme.colors.accentSoft,
            unselectedIconColor = theme.colors.textSecondary,
            unselectedTextColor = theme.colors.textSecondary,
            unselectedContainerColor = theme.colors.surface,
        ),
    )
    val suiteColors = NavigationSuiteDefaults.colors(
        navigationBarContainerColor = theme.colors.surface,
        navigationBarContentColor = theme.colors.textPrimary,
        navigationRailContainerColor = theme.colors.surface,
        navigationRailContentColor = theme.colors.textPrimary,
        navigationDrawerContainerColor = theme.colors.surface,
        navigationDrawerContentColor = theme.colors.textPrimary,
    )
    BoxWithConstraints(modifier = modifier) {
        if (maxWidth < theme.components.page.expandedBreakpoint) {
            WarmPageCompactNavigation(
                items = items,
                selected = selected,
                onSelect = onSelect,
                bottomAccessory = bottomAccessory,
                content = content,
            )
        } else {
            NavigationSuiteScaffold(
                modifier = Modifier.fillMaxSize(),
                navigationSuiteColors = suiteColors,
                containerColor = theme.colors.canvas,
                contentColor = theme.colors.textPrimary,
                navigationSuiteItems = {
                    items.forEach { item ->
                        val isSelected = selected == item.id
                        item(
                            modifier = Modifier.testTag(item.testTag),
                            selected = isSelected,
                            onClick = { onSelect(item.id) },
                            icon = {
                                androidx.compose.material3.Icon(
                                    imageVector = if (isSelected) item.selectedIcon else item.unselectedIcon,
                                    contentDescription = null,
                                )
                            },
                            label = {
                                Text(
                                    text = stringResource(item.labelResource),
                                    style = theme.typography.label,
                                )
                            },
                            colors = itemColors,
                        )
                    }
                },
                content = {
                    Column(Modifier.fillMaxSize()) {
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .fillMaxWidth(),
                        ) {
                            content()
                        }
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            color = theme.colors.surface,
                            contentColor = theme.colors.textPrimary,
                            shape = RectangleShape,
                            tonalElevation = 0.dp,
                        ) {
                            bottomAccessory()
                        }
                    }
                },
            )
        }
    }
}

/**
 * Compact navigation owns the only bottom surface so the mini player and navigation bar share
 * one background, one safe-area boundary, and one elevation context. The adaptive scaffold is
 * retained for larger windows where navigation is a rail or drawer.
 */
@Composable
private fun <T> WarmPageCompactNavigation(
    items: List<WarmPageNavigationItem<T>>,
    selected: T,
    onSelect: (T) -> Unit,
    bottomAccessory: @Composable () -> Unit,
    content: @Composable () -> Unit,
) {
    val theme = WarmPageThemeValues
    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = theme.colors.canvas,
        contentColor = theme.colors.textPrimary,
        bottomBar = {
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("bottom-navigation-shell"),
                color = theme.colors.surface,
                contentColor = theme.colors.textPrimary,
                shape = RectangleShape,
                tonalElevation = 0.dp,
            ) {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .navigationBarsPadding(),
                ) {
                    HorizontalDivider(color = theme.colors.divider)
                    bottomAccessory()
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 64.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        items.forEach { item ->
                            val isSelected = selected == item.id
                            Column(
                                modifier = Modifier
                                    .weight(1f)
                                    .heightIn(min = theme.components.controls.minimumTouchTarget)
                                    .testTag(item.testTag)
                                    .selectable(
                                        selected = isSelected,
                                        onClick = { onSelect(item.id) },
                                        role = Role.Tab,
                                    )
                                    .padding(horizontal = 4.dp, vertical = 6.dp)
                                    .background(
                                        color = if (isSelected) theme.colors.accentSoft else Color.Transparent,
                                        shape = RoundedCornerShape(16.dp),
                                    ),
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                val contentColor = if (isSelected) {
                                    theme.colors.brandAccent
                                } else {
                                    theme.colors.textSecondary
                                }
                                Icon(
                                    imageVector = if (isSelected) item.selectedIcon else item.unselectedIcon,
                                    contentDescription = null,
                                    tint = contentColor,
                                )
                                Text(
                                    text = stringResource(item.labelResource),
                                    color = contentColor,
                                    style = theme.typography.label,
                                    maxLines = 2,
                                    textAlign = TextAlign.Center,
                                )
                            }
                        }
                    }
                }
            }
        },
    ) { contentPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding),
        ) {
            content()
        }
    }
}
