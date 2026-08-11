package com.ermao.library.features.shell

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CollectionsBookmark
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LocalLibrary
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.outlined.CollectionsBookmark
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.LocalLibrary
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationDrawerItemDefaults
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteScaffold
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.navigation3.runtime.NavKey
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.ui.NavDisplay
import com.ermao.library.R
import com.ermao.library.shared.navigation.MobileNavigation
import com.ermao.library.shared.navigation.TabId
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.serialization.Serializable

private data class TabPresentation(
    @StringRes val labelResource: Int,
    val selectedIcon: ImageVector,
    val unselectedIcon: ImageVector,
)

@Serializable
data object HomeRoot : NavKey

@Serializable
data object LibraryRoot : NavKey

@Serializable
data object ShelvesRoot : NavKey

@Serializable
data object MeRoot : NavKey

@Composable
fun MainShell(
    session: AppSession.Authenticated,
    onOpenServers: () -> Unit,
    onLogout: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val homeBackStack = rememberNavBackStack(HomeRoot)
    val libraryBackStack = rememberNavBackStack(LibraryRoot)
    val shelvesBackStack = rememberNavBackStack(ShelvesRoot)
    val meBackStack = rememberNavBackStack(MeRoot)
    var selectedTabValue by rememberSaveable { mutableStateOf(TabId.Home.stableValue) }
    val selectedTab = MobileNavigation.tabIdOrDefault(selectedTabValue)
    val currentBackStack = when (selectedTab) {
        TabId.Home -> homeBackStack
        TabId.Library -> libraryBackStack
        TabId.Shelves -> shelvesBackStack
        TabId.Me -> meBackStack
    }
    val navigationItemColors = NavigationSuiteDefaults.itemColors(
        navigationBarItemColors = NavigationBarItemDefaults.colors(
            selectedIconColor = theme.colors.brandAccent,
            selectedTextColor = theme.colors.brandAccent,
            indicatorColor = theme.colors.accentSoft,
            unselectedIconColor = theme.colors.textSecondary,
            unselectedTextColor = theme.colors.textSecondary,
        ),
        navigationRailItemColors = NavigationRailItemDefaults.colors(
            selectedIconColor = theme.colors.brandAccent,
            selectedTextColor = theme.colors.brandAccent,
            indicatorColor = theme.colors.accentSoft,
            unselectedIconColor = theme.colors.textSecondary,
            unselectedTextColor = theme.colors.textSecondary,
        ),
        navigationDrawerItemColors = NavigationDrawerItemDefaults.colors(
            selectedIconColor = theme.colors.brandAccent,
            selectedTextColor = theme.colors.brandAccent,
            selectedContainerColor = theme.colors.accentSoft,
            unselectedIconColor = theme.colors.textSecondary,
            unselectedTextColor = theme.colors.textSecondary,
        ),
    )

    NavigationSuiteScaffold(
        modifier = modifier,
        navigationSuiteItems = {
            MobileNavigation.orderedRootTabs.forEach { tab ->
                val selected = tab == selectedTab
                val presentation = tab.presentation
                item(
                    selected = selected,
                    onClick = {
                        if (selected) {
                            while (currentBackStack.size > 1) currentBackStack.removeLastOrNull()
                        } else {
                            selectedTabValue = tab.stableValue
                        }
                    },
                    icon = {
                        androidx.compose.material3.Icon(
                            imageVector = if (selected) {
                                presentation.selectedIcon
                            } else {
                                presentation.unselectedIcon
                            },
                            contentDescription = null,
                            modifier = Modifier.testTag("tab-select-${tab.stableValue}"),
                        )
                    },
                    label = { Text(stringResource(presentation.labelResource)) },
                    colors = navigationItemColors,
                )
            }
        },
    ) {
        NavDisplay(
            backStack = currentBackStack,
            onBack = { currentBackStack.removeLastOrNull() },
            entryProvider = entryProvider {
                entry<HomeRoot> { EmptyTabRoot(TabId.Home) }
                entry<LibraryRoot> { EmptyTabRoot(TabId.Library) }
                entry<ShelvesRoot> { EmptyTabRoot(TabId.Shelves) }
                entry<MeRoot> {
                    MeRootScreen(
                        session = session,
                        onOpenServers = onOpenServers,
                        onLogout = onLogout,
                    )
                }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MeRootScreen(
    session: AppSession.Authenticated,
    onOpenServers: () -> Unit,
    onLogout: () -> Unit,
) {
    val theme = WarmPageThemeValues
    var confirmLogout by rememberSaveable { mutableStateOf(false) }
    Scaffold(
        containerColor = theme.colors.canvas,
        topBar = {
            LargeTopAppBar(
                title = { Text(stringResource(R.string.tab_me), style = theme.typography.display) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = theme.colors.canvas,
                    scrolledContainerColor = theme.colors.surface,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(theme.spacing.three)
                .testTag("tab-me"),
        ) {
            Text(session.identity.displayName, style = theme.typography.title)
            Text(session.identity.email, color = theme.colors.textSecondary, style = theme.typography.body)
            Text(session.profile.displayName, color = theme.colors.textSecondary, style = theme.typography.callout)
            Button(
                onClick = onOpenServers,
                modifier = Modifier.fillMaxWidth().padding(top = theme.spacing.three),
            ) { Text(stringResource(R.string.me_servers_action)) }
            TextButton(
                onClick = { confirmLogout = true },
                modifier = Modifier.fillMaxWidth().padding(top = theme.spacing.one),
            ) { Text(stringResource(R.string.logout_action)) }
        }
    }
    if (confirmLogout) {
        AlertDialog(
            onDismissRequest = { confirmLogout = false },
            title = { Text(stringResource(R.string.logout_confirm_title)) },
            text = { Text(stringResource(R.string.logout_confirm_message, session.profile.displayName)) },
            confirmButton = {
                TextButton(onClick = { confirmLogout = false; onLogout() }) {
                    Text(stringResource(R.string.logout_confirm_action))
                }
            },
            dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EmptyTabRoot(tab: TabId) {
    val theme = WarmPageThemeValues
    val presentation = tab.presentation
    Scaffold(
        containerColor = theme.colors.canvas,
        topBar = {
            LargeTopAppBar(
                title = {
                    Text(
                        text = stringResource(presentation.labelResource),
                        color = theme.colors.textPrimary,
                        style = theme.typography.display,
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = theme.colors.canvas,
                    scrolledContainerColor = theme.colors.surface,
                ),
            )
        },
    ) { contentPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .testTag("tab-${tab.stableValue}"),
        )
    }
}

private val TabId.presentation: TabPresentation
    get() = when (this) {
        TabId.Home -> TabPresentation(R.string.tab_home, Icons.Filled.Home, Icons.Outlined.Home)
        TabId.Library -> TabPresentation(
            R.string.tab_library,
            Icons.Filled.LocalLibrary,
            Icons.Outlined.LocalLibrary,
        )
        TabId.Shelves -> TabPresentation(
            R.string.tab_shelves,
            Icons.Filled.CollectionsBookmark,
            Icons.Outlined.CollectionsBookmark,
        )
        TabId.Me -> TabPresentation(R.string.tab_me, Icons.Filled.Person, Icons.Outlined.Person)
    }
