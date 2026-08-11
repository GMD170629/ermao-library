package com.ermao.library.shared.navigation

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class MobileNavigationTest {
    @Test
    fun rootOrderAndStableValuesAreFrozen() {
        assertEquals(
            listOf("home", "library", "shelves", "me"),
            MobileNavigation.orderedRootTabs.map(TabId::stableValue),
        )
    }

    @Test
    fun unknownValuesFailSafeToHome() {
        assertEquals(TabId.Home, MobileNavigation.tabIdOrDefault("future-tab"))
        val intent = assertIs<NavigationIntent.SelectTab>(
            MobileNavigation.parseOrDefault("tab:future-tab"),
        )
        assertEquals(TabId.Home, intent.tabId)
    }
}
