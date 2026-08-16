package com.ermao.library.features.shell

import androidx.navigation3.runtime.NavKey
import com.ermao.library.shared.navigation.TabId
import kotlin.test.assertEquals
import org.junit.Test

class MainShellNavigationTest {
    @Test
    fun viewShelvesActionSelectsTheShelvesRootWithoutResettingOtherTabs() {
        val homeBackStack = mutableListOf<NavKey>(HomeRoot, WorkDetailRoute("home-work"))
        val libraryBackStack = mutableListOf<NavKey>(LibraryRoot, WorkDetailRoute("library-work"))
        val shelvesBackStack = mutableListOf<NavKey>(
            ShelvesRoot,
            WorkDetailRoute("shelf-work"),
            FacetRoute(kind = "Authors", facetId = "author-1"),
        )
        var selectedTab = TabId.Library

        navigateToShelvesRoot(
            shelvesBackStack = shelvesBackStack,
            selectTab = { selectedTab = it },
        )

        assertEquals(TabId.Shelves, selectedTab)
        assertEquals(listOf<NavKey>(ShelvesRoot), shelvesBackStack)
        assertEquals(listOf<NavKey>(HomeRoot, WorkDetailRoute("home-work")), homeBackStack)
        assertEquals(listOf<NavKey>(LibraryRoot, WorkDetailRoute("library-work")), libraryBackStack)
    }
}
