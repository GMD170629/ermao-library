package com.ermao.library.features.shell

import androidx.navigation3.runtime.NavKey
import com.ermao.library.shared.navigation.TabId
import kotlin.test.assertEquals
import org.junit.Test

class MainShellNavigationTest {
    @Test
    fun viewShelvesActionSelectsTheShelvesRootWithoutResettingOtherTabs() {
        val homeBackStack = mutableListOf<NavKey>(HomeRoot, BookDetailRoute("home-work"))
        val libraryBackStack = mutableListOf<NavKey>(LibraryRoot, BookDetailRoute("library-work"))
        val shelvesBackStack = mutableListOf<NavKey>(
            ShelvesRoot,
            BookDetailRoute("shelf-work"),
            FacetRoute(kind = "Authors", facetId = "author-1"),
        )
        var selectedTab = TabId.Library

        navigateToShelvesRoot(
            shelvesBackStack = shelvesBackStack,
            selectTab = { selectedTab = it },
        )

        assertEquals(TabId.Shelves, selectedTab)
        assertEquals(listOf<NavKey>(ShelvesRoot), shelvesBackStack)
        assertEquals(listOf<NavKey>(HomeRoot, BookDetailRoute("home-work")), homeBackStack)
        assertEquals(listOf<NavKey>(LibraryRoot, BookDetailRoute("library-work")), libraryBackStack)
    }
}
