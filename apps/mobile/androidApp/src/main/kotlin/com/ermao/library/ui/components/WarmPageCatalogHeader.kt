package com.ermao.library.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.SecondaryScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import com.ermao.library.ui.theme.WarmPageThemeValues

data class WarmPageCatalogTab<T>(val id: T, val label: String)

/** Native search and secondary tabs, shared by the Library and Shelves catalogs. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun <T> WarmPageCatalogHeader(
    query: String,
    placeholder: String,
    clearLabel: String,
    onQueryChanged: (String) -> Unit,
    onClearQuery: () -> Unit,
    tabs: List<WarmPageCatalogTab<T>>,
    selectedTab: T,
    onSelectTab: (T) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    searchModifier: Modifier = Modifier,
    tabsModifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        WarmPageSearchField(
            value = query,
            placeholder = placeholder,
            clearLabel = clearLabel,
            onValueChange = onQueryChanged,
            onClear = onClearQuery,
            enabled = enabled,
            modifier = searchModifier.padding(horizontal = theme.components.page.compactGutter),
        )
        SecondaryScrollableTabRow(
            selectedTabIndex = tabs.indexOfFirst { it.id == selectedTab }.coerceAtLeast(0),
            containerColor = theme.colors.canvas,
            contentColor = theme.colors.actionAccent,
            edgePadding = theme.components.page.compactGutter,
            modifier = tabsModifier.fillMaxWidth(),
        ) {
            tabs.forEach { tab ->
                key(tab.id) {
                    Tab(
                        selected = tab.id == selectedTab,
                        onClick = { onSelectTab(tab.id) },
                        enabled = enabled,
                        selectedContentColor = theme.colors.actionAccent,
                        unselectedContentColor = theme.colors.textSecondary,
                        // Match the native text field's minimum without fixing text height;
                        // both controls may grow with accessibility font scaling.
                        modifier = Modifier.heightIn(min = OutlinedTextFieldDefaults.MinHeight)
                            .testTag("catalog-tab-${tab.id}"),
                        text = { Text(tab.label, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    )
                }
            }
        }
    }
}
