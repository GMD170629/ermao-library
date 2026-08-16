package com.ermao.library.ui.components

import androidx.annotation.StringRes
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationDrawerItemDefaults
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteDefaults
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteScaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
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
    NavigationSuiteScaffold(
        modifier = modifier,
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
        content = content,
    )
}
