package com.ermao.library.ui.components

import androidx.compose.ui.unit.dp
import kotlin.test.assertEquals
import org.junit.Test

class WarmPageActionsPolicyTest {
    @Test
    fun compactIconActionsReserveRoomForTheEnglishLabelAndTrailingIcon() {
        assertEquals(
            8.dp,
            warmPageActionHorizontalPadding(
                hasIcon = true,
                regularPadding = 24.dp,
                compactPadding = 8.dp,
            ),
        )
        assertEquals(
            24.dp,
            warmPageActionHorizontalPadding(
                hasIcon = false,
                regularPadding = 24.dp,
                compactPadding = 8.dp,
            ),
        )
    }
}
