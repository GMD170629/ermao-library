package com.ermao.library.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.MenuBook
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.clearAndSetSemantics
import com.ermao.library.ui.theme.WarmPageThemeValues

/** Stateless content identity layout. Callers own cover loading, navigation and task actions. */
@Composable
fun ContentListRow(
    title: String,
    modifier: Modifier = Modifier,
    cover: @Composable () -> Unit = { ContentListCoverPlaceholder() },
    actions: @Composable RowScope.() -> Unit = {},
    description: @Composable ColumnScope.() -> Unit,
) {
    val theme = WarmPageThemeValues
    Row(modifier.fillMaxWidth().padding(vertical = theme.spacing.one),
        horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
        verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.width(theme.components.controls.minimumTouchTarget)
            .aspectRatio(theme.metrics.coverAspectRatio).clearAndSetSemantics { }) { cover() }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(theme.spacing.half)) {
            Text(title, style = theme.typography.headline, color = theme.colors.textPrimary,
                maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
            Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.half)) { description() }
        }
        Row(verticalAlignment = Alignment.CenterVertically, content = actions)
    }
}

@Composable
fun ContentListCoverPlaceholder() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Icon(Icons.AutoMirrored.Outlined.MenuBook, null, tint = WarmPageThemeValues.colors.textTertiary)
    }
}
