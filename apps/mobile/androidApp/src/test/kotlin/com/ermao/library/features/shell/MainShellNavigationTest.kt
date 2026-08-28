package com.ermao.library.features.shell

import androidx.navigation3.runtime.NavKey
import com.ermao.library.shared.navigation.TabId
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import com.ermao.library.shared.modules.library.BookContentTarget
import kotlinx.serialization.json.Json
import org.junit.Test

class MainShellNavigationTest {
    @Test
    fun contentDestinationsHaveIsolatedBookNamespaceTabAndNodeIdentities() {
        val root = BookContentRoute("book-1", "server-1", "user-1", 1, "library", BookContentTarget.Root)
        val destinations = listOf(
            root.copy(bookId = "book-2"),
            root.copy(serverIdentity = "server-2"),
            root.copy(userId = "user-2"),
            root.copy(authorizationVersion = 2),
            root.copy(sourceTab = "shelves"),
            root.copy(target = BookContentTarget.Directory("node-1")),
            root.copy(target = BookContentTarget.ResourceDetail("resource-1")),
        )
        destinations.forEach { destination ->
            assertNotEquals(root, destination)
            assertEquals(destination, Json.decodeFromString<BookContentRoute>(Json.encodeToString(destination)))
        }
        assertEquals(root, Json.decodeFromString<BookContentRoute>(Json.encodeToString(root)))
    }

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
