package com.ermao.library.shared.navigation

enum class TabId(val stableValue: String) {
    Home("home"),
    Library("library"),
    Shelves("shelves"),
    Me("me"),
}

sealed interface NavigationIntent {
    data class SelectTab(val tabId: TabId) : NavigationIntent

    data object Back : NavigationIntent
}

object MobileNavigation {
    val orderedRootTabs: List<TabId> = listOf(TabId.Home, TabId.Library, TabId.Shelves, TabId.Me)

    fun tabIdOrDefault(stableValue: String?, defaultTab: TabId = TabId.Home): TabId =
        TabId.entries.firstOrNull { it.stableValue == stableValue } ?: defaultTab

    fun encode(intent: NavigationIntent): String = when (intent) {
        NavigationIntent.Back -> "back"
        is NavigationIntent.SelectTab -> "tab:${intent.tabId.stableValue}"
    }

    fun parseOrDefault(rawValue: String?, defaultTab: TabId = TabId.Home): NavigationIntent {
        if (rawValue == "back") return NavigationIntent.Back
        val tabValue = rawValue?.takeIf { it.startsWith("tab:") }?.removePrefix("tab:")
        return NavigationIntent.SelectTab(tabIdOrDefault(tabValue, defaultTab))
    }
}
