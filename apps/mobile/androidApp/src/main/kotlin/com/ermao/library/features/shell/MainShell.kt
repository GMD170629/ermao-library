package com.ermao.library.features.shell

import com.ermao.library.shared.modules.reader.ReaderFormatSupport
import com.ermao.library.shared.modules.reader.ReaderDeliveryMode

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.navigation3.runtime.NavKey
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.ui.NavDisplay
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ermao.library.R
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.home.application.HomeViewModel
import com.ermao.library.features.home.ui.HomeScreen
import com.ermao.library.features.library.application.FacetViewModel
import com.ermao.library.features.library.application.LibraryViewModel
import com.ermao.library.features.library.application.WorkDetailViewModel
import com.ermao.library.features.library.ui.FacetScreen
import com.ermao.library.features.library.ui.LibraryScreen
import com.ermao.library.features.library.ui.WorkDetailScreen
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.shared.navigation.MobileNavigation
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.navigation.TabId
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsRepository
import com.ermao.library.features.me.application.AndroidMeFeatureFactory
import com.ermao.library.features.me.application.SettingsSideEffects
import com.ermao.library.features.me.model.MeRoute
import com.ermao.library.features.me.platform.AppLocaleController
import com.ermao.library.features.me.ui.AboutScreen
import com.ermao.library.features.me.ui.LanguageScreen
import com.ermao.library.features.me.ui.MeRootScreen
import com.ermao.library.features.me.ui.ProfileScreen
import com.ermao.library.features.me.ui.SecurityScreen
import com.ermao.library.features.administrativesettings.AdministrativeCapability
import com.ermao.library.features.administrativesettings.AdministrativeLocale
import com.ermao.library.features.administrativesettings.AdministrativeSettingsContext
import com.ermao.library.features.administrativesettings.AdministrativeSettingsDestination
import com.ermao.library.features.administrativesettings.AdministrativeSettingsFeatureFactory
import com.ermao.library.features.administrativesettings.AdministrativeSettingsRoute
import com.ermao.library.features.administrativesettings.AdministrativeSettingsSideEffects
import com.ermao.library.features.administrativesettings.AdministrativeSettingsSystemActions
import com.ermao.library.features.administrativesettings.AdministrativeSettingsViewModel
import com.ermao.library.features.administrativesettings.EmailKindleTab
import com.ermao.library.features.administrativesettings.SharedAdministrativeSettingsAdapter
import com.ermao.library.features.administrativesettings.rememberAdministrativeSettingsSystemActions
import com.ermao.library.BuildConfig
import com.ermao.library.features.downloads.application.DownloadCenterViewModel
import com.ermao.library.features.downloads.application.DownloadedBookViewModel
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.infrastructure.AtomicDownloadFileSink
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.ui.DownloadCenterScreen
import com.ermao.library.features.downloads.ui.DownloadedBookScreen
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.toDownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadsRuntime
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import com.ermao.library.features.workmanagement.application.WorkManagementViewModel
import com.ermao.library.features.content.ui.BookCover
import com.ermao.library.features.content.ui.CoverRole
import com.ermao.library.features.content.ui.ContentAreaMessage
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.createAdministrativeSettingsContext
import com.ermao.library.ui.components.WarmPageNavigationItem
import com.ermao.library.ui.components.WarmPageNavigationSuite
import com.ermao.library.ui.components.WarmPageScaffold
import com.ermao.library.ui.components.WarmPageTopBarRole
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
data class ShelfDetailRoute(val shelfId: String) : NavKey

@Serializable
data object MeRoot : NavKey

@Serializable
data class BookDetailRoute(val bookId: String) : NavKey

@Serializable
data class FacetRoute(
    val kind: String,
    val facetId: String,
) : NavKey

@Serializable
data object DownloadsCenterRoute : NavKey

@Serializable
data class DownloadedBookRoute(val bookId: String) : NavKey

@Serializable
data class ReaderUnavailableRoute(
    val resourceId: String,
    val accessKind: String,
) : NavKey

internal fun <T : NavKey> navigateToShelvesRoot(
    shelvesBackStack: MutableList<T>,
    selectTab: (TabId) -> Unit,
) {
    while (shelvesBackStack.size > 1) shelvesBackStack.removeAt(shelvesBackStack.lastIndex)
    selectTab(TabId.Shelves)
}

@Composable
fun MainShell(
    session: AppSession.Authenticated,
    contentRepository: ContentRepository,
    personalSettingsRepository: PersonalSettingsRepository,
    administrativeSettingsRepository: AdministrativeSettingsRepository,
    workManagementRepository: WorkManagementRepository,
    downloadCatalog: AndroidDownloadCatalog,
    downloadFiles: AtomicDownloadFileSink,
    sharedDownloadCatalog: DownloadCatalogRepository,
    localeController: AppLocaleController,
    onSessionUnauthorized: () -> Unit,
    onRefreshSession: suspend () -> Unit,
    onPurgeCurrentNamespace: suspend () -> Unit,
    onLogout: suspend (purgeNamespace: Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    val homeBackStack = rememberNavBackStack(HomeRoot)
    val libraryBackStack = rememberNavBackStack(LibraryRoot)
    val shelvesBackStack = rememberNavBackStack(ShelvesRoot)
    val meBackStack = rememberNavBackStack(MeRoot)
    var selectedTabValue by rememberSaveable { mutableStateOf(TabId.Home.stableValue) }
    val onViewShelves = {
        navigateToShelvesRoot(
            shelvesBackStack = shelvesBackStack,
            selectTab = { selectedTabValue = it.stableValue },
        )
    }
    val selectedTab = MobileNavigation.tabIdOrDefault(selectedTabValue)
    val contentContext = ContentRequestContext(session.profile, session.identity.namespace)
    val downloadNamespace = AndroidDownloadNamespace(
        session.identity.namespace.serverIdentity,
        session.identity.namespace.userId,
        session.identity.namespace.authorizationVersion,
    )
    val appContext = LocalContext.current.applicationContext
    val shelfRepository = remember(appContext) { com.ermao.library.shared.createAndroidShelfRepository(appContext) }
    val shelfCatalogRepository = remember(appContext) { com.ermao.library.shared.createAndroidShelfCatalogRepository(appContext) }
    val sharedDownloadsRuntime = remember(sharedDownloadCatalog) { DownloadsRuntime(sharedDownloadCatalog) }
    val sharedDownloadNamespace = session.identity.namespace.toDownloadNamespace()
    val contentKey = listOf(
        session.identity.namespace.serverIdentity,
        session.identity.namespace.userId,
        session.identity.namespace.authorizationVersion,
    ).joinToString("-")
    val downloadActionsViewModel = remember(contentKey) {
        (appContext.applicationContext as com.ermao.library.ErmaoLibraryApplication).accountDownloads(session)
    }
    val downloadRecordsByResource by downloadActionsViewModel.recordsByResource.collectAsStateWithLifecycle()
    val downloadFailuresByResource by downloadActionsViewModel.failureByResource.collectAsStateWithLifecycle()
    val meViewModel: com.ermao.library.features.me.application.MeViewModel = viewModel(
        key = "me-$contentKey",
        factory = AndroidMeFeatureFactory.viewModelFactory(
            repository = personalSettingsRepository,
            session = session,
            sideEffects = object : SettingsSideEffects {
                override suspend fun refreshSession() = onRefreshSession()
                override suspend fun purgeCurrentNamespace() {
                    downloadActionsViewModel.cancelAllAndJoin()
                    sharedDownloadCatalog.clearNamespace(session.identity.namespace.toDownloadNamespace())
                    onPurgeCurrentNamespace()
                }
                override suspend fun logoutAfterPasswordChange() {
                    downloadActionsViewModel.cancelAllAndJoin()
                    sharedDownloadCatalog.clearNamespace(session.identity.namespace.toDownloadNamespace())
                    onPurgeCurrentNamespace()
                    onLogout(false)
                }
                override suspend fun logout() {
                    downloadActionsViewModel.cancelAllAndJoin()
                    sharedDownloadCatalog.clearNamespace(session.identity.namespace.toDownloadNamespace())
                    onLogout(true)
                }
                override fun requireReauthentication() = onSessionUnauthorized()
            },
            appVersion = "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
        ),
    )
    val meRootState by meViewModel.rootState.collectAsStateWithLifecycle()
    val meProfileState by meViewModel.profileState.collectAsStateWithLifecycle()
    val meSecurityState by meViewModel.securityState.collectAsStateWithLifecycle()
    val meAboutState by meViewModel.aboutState.collectAsStateWithLifecycle()
    val administrativeCapabilities = buildSet {
        add(AdministrativeCapability.ManageEmail)
        add(AdministrativeCapability.ManageKindleQueue)
        if (session.authorization.isAdmin || session.authorization.canManageSystem) {
            add(AdministrativeCapability.ViewAdministration)
        }
        if (session.authorization.isAdmin) add(AdministrativeCapability.ManageUsers)
        if (session.authorization.canManageSystem) {
            add(AdministrativeCapability.ManageLibrarySources)
            add(AdministrativeCapability.ManageImports)
            add(AdministrativeCapability.ManageOrganization)
            add(AdministrativeCapability.ManageMetadata)
            add(AdministrativeCapability.ManageOpds)
            add(AdministrativeCapability.ManageBackups)
            add(AdministrativeCapability.ManageSystem)
            add(AdministrativeCapability.ViewLogs)
            add(AdministrativeCapability.ManageLogs)
        }
    }
    val administrativeLocale = if (session.identity.locale == "zh-CN") {
        AdministrativeLocale.ZhCn
    } else {
        AdministrativeLocale.EnUs
    }
    val sharedAdministrativeContext = createAdministrativeSettingsContext(
        profileId = session.profile.id,
        displayName = session.profile.displayName,
        baseUrl = session.profile.baseUrl.value,
        serverIdentity = session.profile.serverIdentity,
        acceptsInsecureTls = session.profile.tlsMode ==
            com.ermao.library.shared.modules.servers.domain.TlsMode.InsecureSkipAllValidation,
    )
    val administrativeViewModel: AdministrativeSettingsViewModel = viewModel(
        key = "administrative-$contentKey-${administrativeLocale.name}",
        factory = AdministrativeSettingsFeatureFactory.viewModelFactory(
            repository = SharedAdministrativeSettingsAdapter(
                sharedRepository = administrativeSettingsRepository,
                sharedContext = sharedAdministrativeContext,
            ),
            context = AdministrativeSettingsContext(
                profileId = session.profile.id,
                serverIdentity = session.profile.serverIdentity,
                actorId = session.identity.namespace.userId,
                locale = administrativeLocale,
                capabilities = administrativeCapabilities,
            ),
            sideEffects = AdministrativeSettingsSideEffects(onSessionUnauthorized),
        ),
    )
    val administrativeSystemActions = rememberAdministrativeSettingsSystemActions()
    val currentBackStack = when (selectedTab) {
        TabId.Home -> homeBackStack
        TabId.Library -> libraryBackStack
        TabId.Shelves -> shelvesBackStack
        TabId.Me -> meBackStack
    }
    val libraryViewModel: LibraryViewModel = viewModel(
        key = "library-$contentKey",
        factory = LibraryViewModel.factory(contentRepository, contentContext, onSessionUnauthorized),
    )
    val libraryState by libraryViewModel.uiState.collectAsState()
    val openBook: (String) -> Unit = { bookId ->
        val route = BookDetailRoute(bookId)
        val existing = libraryBackStack.indexOf(route)
        if (existing >= 0) {
            while (libraryBackStack.lastIndex > existing) libraryBackStack.removeLastOrNull()
        } else if (libraryBackStack.lastOrNull() is BookDetailRoute) {
            libraryBackStack[libraryBackStack.lastIndex] = route
        } else libraryBackStack.add(route)
    }
    val libraryContent: @Composable (Modifier) -> Unit = { libraryModifier ->
        LibraryScreen(
            state = libraryState,
            repository = contentRepository,
            context = contentContext,
            onSelectLibrary = libraryViewModel::selectLibrary,
            onQueryChanged = libraryViewModel::updateQuery,
            onClearQuery = libraryViewModel::clearQuery,
            onSelectSort = libraryViewModel::selectSort,
            onSelectViewMode = libraryViewModel::selectViewMode,
            onOpenFilter = libraryViewModel::openFilter,
            onUpdateFilterDraft = libraryViewModel::updateFilterDraft,
            onRemoveReadingFilter = libraryViewModel::removeReadingFilter,
            onClearFilters = libraryViewModel::clearFilters,
            onApplyFilter = libraryViewModel::applyFilter,
            onDismissFilter = libraryViewModel::dismissFilter,
            onOpenWork = openBook,
            onOpenFacet = { kind, id ->
                val route = FacetRoute(kind.name, id)
                val existingIndex = libraryBackStack.indexOf(route)
                if (existingIndex >= 0) {
                    while (libraryBackStack.lastIndex > existingIndex) libraryBackStack.removeLastOrNull()
                } else {
                    libraryBackStack.add(route)
                }
            },
            onRetry = libraryViewModel::retry,
            onLoadNextPage = libraryViewModel::loadNextPage,
            onScrollAnchorChanged = libraryViewModel::updateScrollAnchor,
            modifier = libraryModifier,
        )
    }
    val navigationItems = MobileNavigation.orderedRootTabs.map { tab ->
        val presentation = tab.presentation
        WarmPageNavigationItem(
            id = tab,
            labelResource = presentation.labelResource,
            selectedIcon = presentation.selectedIcon,
            unselectedIcon = presentation.unselectedIcon,
            testTag = "tab-select-${tab.stableValue}",
        )
    }
    com.ermao.library.features.workmanagement.BookManagementHost(
        repository = workManagementRepository, context = contentContext,
        canManage = session.authorization.canManageSystem,
        onUnauthorized = onSessionUnauthorized, onRefreshAuthorization = onRefreshSession,
        onChanged = { change ->
            contentRepository.invalidate(contentContext.namespace)
            libraryViewModel.refreshAfterManagement()
            if (change.deleted && change.resourceId == null) {
                listOf(homeBackStack, libraryBackStack, shelvesBackStack, meBackStack).forEach { stack ->
                    val index = stack.indexOfFirst { it is BookDetailRoute && it.bookId == change.bookId }
                    if (index >= 0) while (stack.size > index) stack.removeLastOrNull()
                }
                downloadActionsViewModel.removeBook(change.bookId)
            }
        },
        onOpenKindleSettings = { selectedTabValue = TabId.Me.stableValue; meBackStack.add(AdministrativeSettingsRoute.EmailKindle(EmailKindleTab.Kindle)) },
        onOpenKindleQueue = { selectedTabValue = TabId.Me.stableValue; meBackStack.add(AdministrativeSettingsRoute.KindleQueue) },
    ) {
    WarmPageNavigationSuite(
        items = navigationItems,
        selected = selectedTab,
        onSelect = { tab ->
            if (tab == selectedTab) {
                while (currentBackStack.size > 1) currentBackStack.removeLastOrNull()
            } else {
                selectedTabValue = tab.stableValue
            }
        },
        modifier = modifier,
    ) {
        NavDisplay(
            backStack = currentBackStack,
            onBack = { currentBackStack.removeLastOrNull() },
            entryProvider = entryProvider {
                entry<HomeRoot> {
                    val homeViewModel: HomeViewModel = viewModel(
                        key = "home-$contentKey",
                        factory = HomeViewModel.factory(contentRepository, contentContext, appContext, onSessionUnauthorized),
                    )
                    val managementRevision = com.ermao.library.features.workmanagement.managementRevision()
    val managementChange = com.ermao.library.features.workmanagement.managementChange()
    androidx.compose.runtime.LaunchedEffect(managementRevision) { if (managementRevision > 0 && managementChange != null) homeViewModel.refreshAfterManagement(managementChange.bookId, managementChange.readingStatusChanged) }
    val homeState by homeViewModel.uiState.collectAsState()
                    HomeScreen(
                        state = homeState,
                        repository = contentRepository,
                        context = contentContext,
                        onOpenBook = { bookId ->
                            val route = BookDetailRoute(bookId)
                            if (homeBackStack.lastOrNull() != route) homeBackStack.add(route)
                        },
                        onContinueReading = { item ->
                            val resourceId = item.resumeResourceId
                            if (resourceId.isNullOrBlank()) {
                                val route = BookDetailRoute(item.book.id)
                                if (homeBackStack.lastOrNull() != route) homeBackStack.add(route)
                            } else {
                                appContext.startActivity(
                                    ReaderActivity.createServerIntent(appContext, session.profile.id, resourceId),
                                )
                            }
                        },
                        onOpenLibrary = { selectedTabValue = TabId.Library.stableValue },
                        onRetry = homeViewModel::retry,
                        onRefresh = homeViewModel::refresh,
                    )
                }
                entry<LibraryRoot> {
                    libraryContent(Modifier.fillMaxSize())
                }
                entry<ShelvesRoot> {
                    com.ermao.library.features.shelves.ShelfCatalogRoute(
                        repository = shelfCatalogRepository, contentRepository = contentRepository, context = contentContext,
                        onUnauthorized = onSessionUnauthorized, onBack = {},
                        onOpenShelf = { id -> shelvesBackStack.add(ShelfDetailRoute(id)) },
                        onOpenBook = { id -> shelvesBackStack.add(BookDetailRoute(id)) },
                    )
                }
                entry<ShelfDetailRoute> { route ->
                    com.ermao.library.features.shelves.ShelfCatalogRoute(
                        repository = shelfCatalogRepository, contentRepository = contentRepository, context = contentContext,
                        shelfId = route.shelfId, onUnauthorized = onSessionUnauthorized,
                        onBack = { shelvesBackStack.removeLastOrNull() },
                        onOpenShelf = { id ->
                            val target = ShelfDetailRoute(id)
                            if (shelvesBackStack.lastOrNull() != target) shelvesBackStack.add(target)
                        },
                        onOpenBook = { id ->
                            val target = BookDetailRoute(id)
                            if (shelvesBackStack.lastOrNull() != target) shelvesBackStack.add(target)
                        },
                    )
                }
                entry<MeRoot> {
                    MeRootScreen(
                        state = meRootState,
                        onOpenProfile = { meBackStack.add(MeRoute.Profile) },
                        onOpenSecurity = { meBackStack.add(MeRoute.Security) },
                        onOpenLanguage = { meBackStack.add(MeRoute.Language) },
                        onOpenAbout = { meBackStack.add(MeRoute.About) },
                        onOpenDownloads = { meBackStack.add(DownloadsCenterRoute) },
                        canOpenAdministration = AdministrativeCapability.ViewAdministration in administrativeCapabilities,
                        onOpenEmailAndKindle = {
                            meBackStack.add(AdministrativeSettingsRoute.EmailKindle(EmailKindleTab.Kindle))
                        },
                        onOpenKindleQueue = { meBackStack.add(AdministrativeSettingsRoute.KindleQueue) },
                        onOpenAdministration = { meBackStack.add(AdministrativeSettingsRoute.Root) },
                        onRetry = meViewModel::retryLoad,
                        modifier = Modifier.testTag("tab-me"),
                    )
                }
                entry<MeRoute.Profile> {
                    meRootState.account?.let { account ->
                        ProfileScreen(
                            state = meProfileState,
                            account = account,
                            avatarBytes = meRootState.avatarBytes,
                            onBack = { meBackStack.removeLastOrNull() },
                            onDisplayNameChanged = meViewModel::updateDisplayName,
                            onAvatarReady = meViewModel::stageAvatar,
                            onSaveName = meViewModel::saveName,
                            onUploadAvatar = meViewModel::uploadAvatar,
                            onDeleteAvatar = meViewModel::deleteAvatar,
                        )
                    }
                }
                entry<MeRoute.Security> {
                    SecurityScreen(
                        state = meSecurityState,
                        serverName = meRootState.serverName,
                        onBack = { meBackStack.removeLastOrNull() },
                        onEmailChanged = meViewModel::updateEmail,
                        onEmailCurrentPasswordChanged = meViewModel::updateEmailCurrentPassword,
                        onCurrentPasswordChanged = meViewModel::updateSecurityCurrentPassword,
                        onNewPasswordChanged = meViewModel::updateNewPassword,
                        onPasswordConfirmationChanged = meViewModel::updatePasswordConfirmation,
                        onSaveEmail = meViewModel::saveEmail,
                        onSavePassword = meViewModel::savePassword,
                        onLogout = meViewModel::logout,
                    )
                }
                entry<MeRoute.Language> {
                    LanguageScreen(
                        selected = meRootState.locale,
                        onBack = { meBackStack.removeLastOrNull() },
                        onSelect = { meViewModel.selectLocale(it, localeController::apply) },
                    )
                }
                entry<MeRoute.About> {
                    AboutScreen(
                        state = meAboutState,
                        onBack = { meBackStack.removeLastOrNull() },
                        onRetry = meViewModel::loadAbout,
                    )
                }
                entry<DownloadsCenterRoute> {
                    val downloadsViewModel: DownloadCenterViewModel = viewModel(
                        key = "downloads-$contentKey",
                        factory = DownloadCenterViewModel.factory(downloadCatalog, downloadNamespace) { record ->
                            downloadFiles.hasLocalArtifact(record.localReference, record.expectedBytes)
                        },
                    )
                    val downloadsState by downloadsViewModel.uiState.collectAsStateWithLifecycle()
                    DownloadCenterScreen(
                        state = downloadsState,
                        onBack = { meBackStack.removeLastOrNull() },
                        onQueryChanged = downloadsViewModel::updateQuery,
                        onClearQuery = downloadsViewModel::clearQuery,
                        onOpenBook = { bookId -> meBackStack.add(DownloadedBookRoute(bookId)) },
                        onRetry = downloadsViewModel::retry,
                        onCancelDownload = downloadActionsViewModel::cancelDownload,
                        onRemoveDownload = downloadActionsViewModel::removeDownload,
                        onRetryDownload = downloadActionsViewModel::requestDownload,
                    )
                }
                entry<DownloadedBookRoute> { route ->
                    val downloadedBookViewModel: DownloadedBookViewModel = viewModel(
                        key = "downloaded-book-$contentKey-${route.bookId}",
                        factory = DownloadedBookViewModel.factory(downloadCatalog, downloadNamespace, route.bookId) { record ->
                            downloadFiles.hasLocalArtifact(record.localReference, record.expectedBytes)
                        },
                    )
                    val downloadedBookState by downloadedBookViewModel.uiState.collectAsStateWithLifecycle()
                    DownloadedBookScreen(
                        state = downloadedBookState,
                        onBack = { meBackStack.removeLastOrNull() },
                        onOpenResource = { record ->
                            if (ReaderFormatSupport.canReadOriginal(record.readerType, record.format)) {
                                appContext.startActivity(
                                    ReaderActivity.createManagedDownloadIntent(
                                        context = appContext,
                                        profileId = session.profile.id,
                                        bookId = record.bookId,
                                        resourceId = record.resourceId,
                                        assetId = record.assetId,
                                        displayTitle = record.resourceTitle,
                                        localReference = checkNotNull(record.localReference),
                                        sourceFormat = record.format,
                                    ),
                                )
                            } else {
                                meBackStack.add(ReaderUnavailableRoute(record.resourceId, record.readerType))
                            }
                        },
                    )
                }
                entry<ReaderUnavailableRoute> { route ->
                    ReaderUnavailableScreen(
                        isRemoteStream = route.accessKind.equals("pdf", true) || route.accessKind.equals("comic", true),
                        onBack = { meBackStack.removeLastOrNull() },
                    )
                }
                entry<AdministrativeSettingsRoute.Root> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.EmailKindle> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.KindleQueue> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.Users> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.UserEdit> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.UserAccess> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.LibrarySources> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.LibrarySourceEdit> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.ServerDirectory> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.ImportTasks> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.ImportTaskDetail> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.ImportScanJobs> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.ImportScanJob> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.ImportPreferences> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.OrganizeQueue> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.OrganizeCandidates> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.OrganizeRuns> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.RecognitionPolicy> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.LibraryOperations> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.CategoryGovernance> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.MetadataProviders> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.MetadataProviderEdit> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.Opds> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.Backups> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.DetailOrder> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.Health> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<AdministrativeSettingsRoute.Logs> { route ->
                    AdministrativeDestination(route, administrativeViewModel, administrativeLocale, administrativeCapabilities, administrativeSystemActions, meBackStack)
                }
                entry<BookDetailRoute> { route ->
                    BoxWithConstraints {
                        val showMaster = selectedTab == TabId.Library &&
                            maxWidth >= WarmPageThemeValues.components.page.expandedBreakpoint
                        Row(Modifier.fillMaxSize()) {
                            if (showMaster) libraryContent(Modifier.weight(0.44f))
                            Box(Modifier.weight(if (showMaster) 0.56f else 1f).fillMaxSize()) {
                                BookContentNavigation(
                                    sourceTab = selectedTab,
                                    bookId = route.bookId, repository = contentRepository, shelfRepository = shelfRepository,
                                    context = contentContext, managementRepository = workManagementRepository,
                                    downloads = downloadActionsViewModel, canManageSystem = session.authorization.canManageSystem,
                                    onBack = { currentBackStack.removeLastOrNull() }, onUnauthorized = onSessionUnauthorized,
                                    onViewShelves = onViewShelves,
                                    onOpenFacet = { kind, id -> currentBackStack.add(FacetRoute(kind.name, id)) },
                                    onOpenResource = { resource ->
                                        openResource(appContext, session.profile.id, resource) { currentBackStack.add(it) }
                                    },
                                    onOpenReadingUnit = { resource, unit ->
                                        openResource(appContext, session.profile.id, resource, unit) { currentBackStack.add(it) }
                                    },
                                    onOpenDownload = { record ->
                                        openDownloadedResource(appContext, session.profile.id, record) { currentBackStack.add(it) }
                                    },
                                )
                            }
                        }
                    }
                }
                entry<FacetRoute> { route ->
                    val kind = LibraryScope.entries.firstOrNull { it.name == route.kind } ?: LibraryScope.Series
                    val facetViewModel: FacetViewModel = viewModel(
                        key = "facet-$contentKey-${route.kind}-${route.facetId}",
                        factory = FacetViewModel.factory(contentRepository, contentContext, kind, route.facetId, onSessionUnauthorized),
                    )
                    val managementRevision = com.ermao.library.features.workmanagement.managementRevision()
    androidx.compose.runtime.LaunchedEffect(managementRevision) { if (managementRevision > 0) facetViewModel.refreshAfterManagement() }
    val facetState by facetViewModel.uiState.collectAsState()
                    FacetScreen(
                        kind = kind,
                        state = facetState,
                        repository = contentRepository,
                        context = contentContext,
                        onBack = { currentBackStack.removeLastOrNull() },
                        onOpenWork = { bookId ->
                            val route = BookDetailRoute(bookId)
                            val existingIndex = currentBackStack.indexOf(route)
                            if (existingIndex >= 0) {
                                while (currentBackStack.lastIndex > existingIndex) currentBackStack.removeLastOrNull()
                            } else {
                                currentBackStack.add(route)
                            }
                        },
                        onRetry = facetViewModel::retry,
                        onLoadNextPage = facetViewModel::loadNextPage,
                    )
                }
            },
        )
    }
    }
}

private fun openResource(
    context: android.content.Context,
    profileId: String,
    resource: ResourceContent,
    unit: com.ermao.library.shared.modules.library.domain.ReadingUnit? = null,
    onUnavailable: (ReaderUnavailableRoute) -> Unit,
) {
    if (ReaderFormatSupport.deliveryMode(resource.readerType, resource.format) != ReaderDeliveryMode.Unsupported) {
        context.startActivity(ReaderActivity.createServerIntent(context, profileId, resource.id,
            unit?.let { com.ermao.library.shared.modules.reader.readingUnitLaunchTarget(resource.readerType, it.href, it.metadata.pageNumber) }))
    } else {
        onUnavailable(ReaderUnavailableRoute(resource.id, resource.readerType))
    }
}

private fun openDownloadedResource(
    context: android.content.Context,
    profileId: String,
    record: com.ermao.library.features.downloads.model.AndroidDownloadRecord,
    onUnavailable: (ReaderUnavailableRoute) -> Unit,
) {
    val localReference = record.localReference
    if (!record.isReadable || localReference.isNullOrBlank()) return
    if (ReaderFormatSupport.canReadOriginal(record.readerType, record.format)) {
        context.startActivity(
            ReaderActivity.createManagedDownloadIntent(
                context = context,
                profileId = profileId,
                bookId = record.bookId,
                resourceId = record.resourceId,
                assetId = record.assetId,
                displayTitle = record.resourceTitle,
                localReference = localReference,
                sourceFormat = record.format,
            ),
        )
    } else {
        onUnavailable(ReaderUnavailableRoute(record.resourceId, record.readerType))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderUnavailableScreen(
    isRemoteStream: Boolean,
    onBack: () -> Unit,
) {
    val theme = WarmPageThemeValues
    Scaffold(
        containerColor = theme.colors.canvas,
        topBar = {
            androidx.compose.material3.TopAppBar(
                title = { Text(stringResource(R.string.reader_not_implemented_title)) },
                navigationIcon = {
                    androidx.compose.material3.IconButton(onClick = onBack) {
                        androidx.compose.material3.Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            stringResource(R.string.navigate_back),
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = theme.colors.canvas),
            )
        },
    ) { padding ->
        ContentAreaMessage(
            title = stringResource(R.string.reader_not_implemented_title),
            message = stringResource(
                if (isRemoteStream) R.string.work_reader_renderer_pending else R.string.reader_not_implemented_message,
            ),
            modifier = Modifier.padding(padding),
        )
    }
}

@Composable
private fun AdministrativeDestination(
    route: AdministrativeSettingsRoute,
    viewModel: AdministrativeSettingsViewModel,
    locale: AdministrativeLocale,
    capabilities: Set<AdministrativeCapability>,
    systemActions: AdministrativeSettingsSystemActions,
    backStack: MutableList<NavKey>,
) {
    AdministrativeSettingsDestination(
        route = route,
        viewModel = viewModel,
        locale = locale,
        capabilities = capabilities,
        systemActions = systemActions,
        onNavigate = { destination ->
            if (backStack.lastOrNull() != destination) backStack.add(destination)
        },
        onReplace = { destination ->
            backStack.removeLastOrNull()
            backStack.add(destination)
        },
        onBack = { backStack.removeLastOrNull() },
    )
}

@Composable
private fun EmptyTabRoot(tab: TabId) {
    val presentation = tab.presentation
    WarmPageScaffold(
        role = WarmPageTopBarRole.Root,
        title = stringResource(presentation.labelResource),
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
