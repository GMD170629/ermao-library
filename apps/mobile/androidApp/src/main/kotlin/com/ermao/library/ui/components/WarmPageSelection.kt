package com.ermao.library.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ermao.library.ui.theme.WarmPageThemeValues

data class WarmPageChoice<T>(
    val value: T,
    val label: String,
    val enabled: Boolean = true,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun <T> WarmPageSegmentedControl(
    options: List<WarmPageChoice<T>>,
    selected: T,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val theme = WarmPageThemeValues
    val fontScale = LocalDensity.current.fontScale
    val segmentHeight = when {
        fontScale >= 1.75f -> 128.dp
        fontScale >= 1.2f -> 72.dp
        else -> theme.components.controls.segmentedMinimumHeight
    }
    SingleChoiceSegmentedButtonRow(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = theme.components.controls.segmentedMinimumHeight),
    ) {
        options.forEachIndexed { index, option ->
            SegmentedButton(
                selected = selected == option.value,
                onClick = { onSelect(option.value) },
                enabled = enabled && option.enabled,
                shape = when {
                    options.size == 1 -> RoundedCornerShape(theme.radii.control)
                    index == 0 -> RoundedCornerShape(
                        topStart = theme.radii.control,
                        bottomStart = theme.radii.control,
                    )
                    index == options.lastIndex -> RoundedCornerShape(
                        topEnd = theme.radii.control,
                        bottomEnd = theme.radii.control,
                    )
                    else -> RoundedCornerShape(theme.spacing.none)
                },
                colors = SegmentedButtonDefaults.colors(
                    activeContainerColor = theme.colors.accentSoft,
                    activeContentColor = theme.colors.brandAccent,
                    activeBorderColor = theme.colors.accentSoft,
                    inactiveContainerColor = theme.colors.canvas,
                    inactiveContentColor = theme.colors.textPrimary,
                    inactiveBorderColor = theme.colors.divider,
                ),
                border = BorderStroke(
                    theme.components.dividerThickness,
                    if (selected == option.value) theme.colors.accentSoft else theme.colors.divider,
                ),
                icon = {},
                label = {
                    Text(
                        text = option.label,
                        style = theme.typography.label,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                        textAlign = TextAlign.Center,
                    )
                },
                modifier = Modifier
                    .weight(1f)
                    .height(segmentHeight),
            )
        }
    }
}
