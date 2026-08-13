package com.ermao.library.features.shell

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
import androidx.compose.runtime.DisposableEffect
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
import androidx.compose.ui.unit.dp
import androidx.navigation3.runtime.NavKey
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.ui.NavDisplay
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ermao.library.R
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.VolumeContent
import com.ermao.library.features.content.model.WorkCard
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
import com.ermao.library.features.downloads.application.DownloadedWorkViewModel
import com.ermao.library.features.downloads.application.DownloadActionsViewModel
import com.ermao.library.features.downloads.application.AndroidReaderAccessOutcome
import com.ermao.library.features.downloads.presentation.DownloadPreparationActivity
import com.ermao.library.features.downloads.infrastructure.AndroidDownloadCatalog
import com.ermao.library.features.downloads.infrastructure.AtomicDownloadFileSink
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.DownloadReaderEntryAction
import com.ermao.library.features.downloads.model.downloadReaderEntryAction
import com.ermao.library.features.downloads.ui.DownloadCenterScreen
import com.ermao.library.features.downloads.ui.DownloadedWorkScreen
import com.ermao.library.shared.core.network.AndroidEncryptedCookieVault
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.modules.downloads.DownloadCatalogRepository
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.createDownloadsGateway
import com.ermao.library.shared.modules.downloads.toDownloadNamespace
import com.ermao.library.features.content.ui.ContentAreaMessage
import com.ermao.library.shared.modules.administrativesettings.AdministrativeSettingsRepository
import com.ermao.library.shared.modules.administrativesettings.createAdministrativeSettingsContext
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

@Serializable
data class WorkDetailRoute(val workId: String) : NavKey

@Serializable
data class FacetRoute(
    val kind: String,
    val facetId: String,
) : NavKey

@Serializable
data object DownloadsCenterRoute : NavKey

@Serializable
data class DownloadedWorkRoute(val workId: String) : NavKey

@Serializable
data class ReaderUnavailableRoute(
    val volumeId: String,
    val accessKind: String,
) : NavKey

@Composable
fun MainShell(
    session: AppSession.Authenticated,
    contentRepository: ContentRepository,
    personalSettingsRepository: PersonalSettingsRepository,
    administrativeSettingsRepository: AdministrativeSettingsRepository,
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
    val theme = WarmPageThemeValues
    val homeBackStack = rememberNavBackStack(HomeRoot)
    val libraryBackStack = rememberNavBackStack(LibraryRoot)
    val shelvesBackStack = rememberNavBackStack(ShelvesRoot)
    val meBackStack = rememberNavBackStack(MeRoot)
    var selectedTabValue by rememberSaveable { mutableStateOf(TabId.Home.stableValue) }
    val selectedTab = MobileNavigation.tabIdOrDefault(selectedTabValue)
    val contentContext = ContentRequestContext(session.profile, session.identity.namespace)
    val downloadNamespace = AndroidDownloadNamespace(
        session.identity.namespace.serverIdentity,
        session.identity.namespace.userId,
        session.identity.namespace.authorizationVersion,
    )
    val appContext = LocalContext.current.applicationContext
    val shelfRepository = remember(appContext) { com.ermao.library.shared.createAndroidShelfRepository(appContext) }
    val contentKey = listOf(
        session.identity.namespace.serverIdentity,
        session.identity.namespace.userId,
        session.identity.namespace.authorizationVersion,
    ).joinToString("-")
    val downloadActionsViewModel: DownloadActionsViewModel = viewModel(
        key = "download-actions-$contentKey",
        factory = DownloadActionsViewModel.factory(
            androidCatalog = downloadCatalog,
            sharedCatalog = sharedDownloadCatalog,
            sink = downloadFiles,
            gateway = createDownloadsGateway(
                ApiClientFactory(AndroidEncryptedCookieVault(appContext), requestTimeoutMillis = 30L * 60L * 1000L),
                session.profile,
            ),
            context = DownloadRequestContext(session.profile, session.identity.namespace.toDownloadNamespace()),
        ),
    )
    val downloadRecordsByVolume by downloadActionsViewModel.recordsByVolume.collectAsStateWithLifecycle()
    val downloadFailuresByVolume by downloadActionsViewModel.failureByVolume.collectAsStateWithLifecycle()
    DisposableEffect(downloadActionsViewModel) {
        onDispose(downloadActionsViewModel::cancelAll)
    }
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
                entry<HomeRoot> {
                    val homeViewModel: HomeViewModel = viewModel(
                        key = "home-$contentKey",
                        factory = HomeViewModel.factory(contentRepository, contentContext, appContext, onSessionUnauthorized),
                    )
                    val homeState by homeViewModel.uiState.collectAsState()
                    HomeScreen(
                        state = homeState,
                        repository = contentRepository,
                        context = contentContext,
                        onOpenWork = { workId ->
                            val route = WorkDetailRoute(workId)
                            if (homeBackStack.lastOrNull() != route) homeBackStack.add(route)
                        },
                        onOpenLibrary = { selectedTabValue = TabId.Library.stableValue },
                        onRetry = homeViewModel::retry,
                        onRefresh = homeViewModel::refresh,
                    )
                }
                entry<LibraryRoot> {
                    val libraryViewModel: LibraryViewModel = viewModel(
                        key = "library-$contentKey",
                        factory = LibraryViewModel.factory(contentRepository, contentContext, onSessionUnauthorized),
                    )
                    val libraryState by libraryViewModel.uiState.collectAsState()
                    BoxWithConstraints {
                        val expanded = maxWidth >= 840.dp
                        val openWork: (String) -> Unit = { workId ->
                            if (expanded) {
                                libraryViewModel.selectWork(workId)
                            } else {
                                val route = WorkDetailRoute(workId)
                                val existingIndex = libraryBackStack.indexOf(route)
                                if (existingIndex >= 0) {
                                    while (libraryBackStack.lastIndex > existingIndex) libraryBackStack.removeLastOrNull()
                                } else {
                                    libraryBackStack.add(route)
                                }
                            }
                        }
                        val libraryContent: @Composable (Modifier) -> Unit = { libraryModifier ->
                            LibraryScreen(
                                state = libraryState,
                                repository = contentRepository,
                                context = contentContext,
                                onSelectScope = libraryViewModel::selectScope,
                                onQueryChanged = libraryViewModel::updateQuery,
                                onClearQuery = libraryViewModel::clearQuery,
                                onSelectSort = libraryViewModel::selectSort,
                                onSelectViewMode = libraryViewModel::selectViewMode,
                                onOpenFilter = libraryViewModel::openFilter,
                                onUpdateFilterDraft = libraryViewModel::updateFilterDraft,
                                onRemoveMediaFilter = libraryViewModel::removeMediaFilter,
                                onRemoveReadingFilter = libraryViewModel::removeReadingFilter,
                                onClearFilters = libraryViewModel::clearFilters,
                                onApplyFilter = libraryViewModel::applyFilter,
                                onDismissFilter = libraryViewModel::dismissFilter,
                                onOpenWork = openWork,
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
                        if (expanded) {
                            Row(Modifier.fillMaxSize()) {
                                libraryContent(Modifier.weight(0.44f))
                                Box(Modifier.weight(0.56f).fillMaxSize()) {
                                    libraryState.selectedWorkId?.let { workId ->
                                        val detailViewModel: WorkDetailViewModel = viewModel(
                                            key = "expanded-work-$contentKey-$workId",
                                            factory = WorkDetailViewModel.factory(
                                                contentRepository,
                                                shelfRepository,
                                                contentContext,
                                                appContext,
                                                workId,
                                                onSessionUnauthorized,
                                            ),
                                        )
                                        val detailState by detailViewModel.uiState.collectAsState()
                                        WorkDetailScreen(
                                            state = detailState,
                                            repository = contentRepository,
                                            context = contentContext,
                                            onBack = { libraryViewModel.selectWork(null) },
                                            onSelectMedia = detailViewModel::selectMedia,
                                            onSelectVolume = detailViewModel::selectVolume,
                                            onOpenShelfPicker = detailViewModel::openShelfPicker,
                                            onDismissShelfPicker = detailViewModel::dismissShelfPicker,
                                            onToggleShelf = detailViewModel::toggleShelf,
                                            onSaveShelves = detailViewModel::saveShelves,
                                            onOpenFacet = { kind, id -> libraryBackStack.add(FacetRoute(kind.name, id)) },
                                            onRetry = detailViewModel::retry,
                                            onRefresh = detailViewModel::refresh,
                                            downloadRecordsByVolume = downloadRecordsByVolume,
                                            downloadFailuresByVolume = downloadFailuresByVolume,
                                            onDownloadVolume = downloadActionsViewModel::requestDownload,
                                            onCancelDownload = downloadActionsViewModel::cancelDownload,
                                            onOpenSelectedVolume = { volume ->
                                                detailState.content?.work?.let { work ->
                                                    openWorkVolume(
                                                        context = appContext,
                                                        profileId = session.profile.id,
                                                        work = work,
                                                        volume = volume,
                                                        existing = downloadRecordsByVolume[volume.id],
                                                        files = downloadFiles,
                                                        requestAccess = downloadActionsViewModel::requestReaderAccess,
                                                        onUnavailable = { libraryBackStack.add(it) },
                                                    )
                                                }
                                            },
                                        )
                                    }
                                }
                            }
                        } else {
                            libraryContent(Modifier.fillMaxSize())
                        }
                    }
                }
                entry<ShelvesRoot> { EmptyTabRoot(TabId.Shelves) }
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
                            downloadFiles.isVerifiedLocalArtifact(record.localReference, record.expectedBytes)
                        },
                    )
                    val downloadsState by downloadsViewModel.uiState.collectAsStateWithLifecycle()
                    DownloadCenterScreen(
                        state = downloadsState,
                        onBack = { meBackStack.removeLastOrNull() },
                        onQueryChanged = downloadsViewModel::updateQuery,
                        onClearQuery = downloadsViewModel::clearQuery,
                        onOpenWork = { workId -> meBackStack.add(DownloadedWorkRoute(workId)) },
                        onRetry = downloadsViewModel::retry,
                        onCancelDownload = downloadActionsViewModel::cancelDownload,
                        onRetryDownload = downloadActionsViewModel::requestDownload,
                        onRemoveDownload = downloadActionsViewModel::removeDownload,
                    )
                }
                entry<DownloadedWorkRoute> { route ->
                    val downloadedWorkViewModel: DownloadedWorkViewModel = viewModel(
                        key = "downloaded-work-$contentKey-${route.workId}",
                        factory = DownloadedWorkViewModel.factory(downloadCatalog, downloadNamespace, route.workId) { record ->
                            downloadFiles.isVerifiedLocalArtifact(record.localReference, record.expectedBytes)
                        },
                    )
                    val downloadedWorkState by downloadedWorkViewModel.uiState.collectAsStateWithLifecycle()
                    DownloadedWorkScreen(
                        state = downloadedWorkState,
                        onBack = { meBackStack.removeLastOrNull() },
                        onOpenVolume = { volume ->
                            if (volume.readerType.equals("reflowable", true) && volume.format.equals("EPUB", true)) {
                                appContext.startActivity(
                                    ReaderActivity.createManagedDownloadIntent(
                                        context = appContext,
                                        profileId = session.profile.id,
                                        workId = volume.workId,
                                        volumeId = volume.volumeId,
                                        displayTitle = volume.workTitle,
                                        localReference = checkNotNull(volume.localReference),
                                        serverContentFingerprint = volume.contentFingerprint,
                                        expectedBytes = volume.expectedBytes,
                                    ),
                                )
                            } else {
                                meBackStack.add(ReaderUnavailableRoute(volume.volumeId, volume.readerType))
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
                entry<AdministrativeSettingsRoute.Duplicates> { route ->
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
                entry<AdministrativeSettingsRoute.MetadataPipeline> { route ->
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
                entry<WorkDetailRoute> { route ->
                    val detailViewModel: WorkDetailViewModel = viewModel(
                        key = "work-$contentKey-${route.workId}",
                        factory = WorkDetailViewModel.factory(contentRepository, shelfRepository, contentContext, appContext, route.workId, onSessionUnauthorized),
                    )
                    val detailState by detailViewModel.uiState.collectAsState()
                    WorkDetailScreen(
                        state = detailState,
                        repository = contentRepository,
                        context = contentContext,
                        onBack = { currentBackStack.removeLastOrNull() },
                        onSelectMedia = detailViewModel::selectMedia,
                        onSelectVolume = detailViewModel::selectVolume,
                        onOpenShelfPicker = detailViewModel::openShelfPicker,
                        onDismissShelfPicker = detailViewModel::dismissShelfPicker,
                        onToggleShelf = detailViewModel::toggleShelf,
                        onSaveShelves = detailViewModel::saveShelves,
                        onOpenFacet = { kind, id ->
                            val route = FacetRoute(kind.name, id)
                            val existingIndex = currentBackStack.indexOf(route)
                            if (existingIndex >= 0) {
                                while (currentBackStack.lastIndex > existingIndex) currentBackStack.removeLastOrNull()
                            } else {
                                currentBackStack.add(route)
                            }
                        },
                        onRetry = detailViewModel::retry,
                        onRefresh = detailViewModel::refresh,
                        downloadRecordsByVolume = downloadRecordsByVolume,
                        downloadFailuresByVolume = downloadFailuresByVolume,
                        onDownloadVolume = downloadActionsViewModel::requestDownload,
                        onCancelDownload = downloadActionsViewModel::cancelDownload,
                        onOpenSelectedVolume = { volume ->
                            detailState.content?.work?.let { work ->
                                openWorkVolume(
                                    context = appContext,
                                    profileId = session.profile.id,
                                    work = work,
                                    volume = volume,
                                    existing = downloadRecordsByVolume[volume.id],
                                    files = downloadFiles,
                                    requestAccess = downloadActionsViewModel::requestReaderAccess,
                                    onUnavailable = { currentBackStack.add(it) },
                                )
                            }
                        },
                    )
                }
                entry<FacetRoute> { route ->
                    val kind = LibraryScope.entries.firstOrNull { it.name == route.kind } ?: LibraryScope.Series
                    val facetViewModel: FacetViewModel = viewModel(
                        key = "facet-$contentKey-${route.kind}-${route.facetId}",
                        factory = FacetViewModel.factory(contentRepository, contentContext, kind, route.facetId, onSessionUnauthorized),
                    )
                    val facetState by facetViewModel.uiState.collectAsState()
                    FacetScreen(
                        kind = kind,
                        state = facetState,
                        repository = contentRepository,
                        context = contentContext,
                        onBack = { currentBackStack.removeLastOrNull() },
                        onOpenWork = { workId ->
                            val route = WorkDetailRoute(workId)
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

private fun AndroidReaderAccessOutcome.toReaderRoute(volumeId: String): ReaderUnavailableRoute? = when (this) {
    is AndroidReaderAccessOutcome.LocalArtifact -> ReaderUnavailableRoute(volumeId, readerType)
    is AndroidReaderAccessOutcome.RemoteStream -> ReaderUnavailableRoute(volumeId, readerType)
    AndroidReaderAccessOutcome.DownloadRequired -> null
    is AndroidReaderAccessOutcome.Unavailable -> ReaderUnavailableRoute(volumeId, "unavailable")
}

private fun openWorkVolume(
    context: android.content.Context,
    profileId: String,
    work: WorkCard,
    volume: VolumeContent,
    existing: com.ermao.library.features.downloads.model.AndroidDownloadRecord?,
    files: AtomicDownloadFileSink,
    requestAccess: (String, Boolean, (AndroidReaderAccessOutcome) -> Unit) -> Unit,
    onUnavailable: (ReaderUnavailableRoute) -> Unit,
) {
    fun openPreparation() {
        context.startActivity(
            DownloadPreparationActivity.createIntent(
                context = context,
                profileId = profileId,
                workId = work.id,
                workTitle = work.title,
                author = work.author,
                coverApiPath = work.coverUrl,
                volumeId = volume.id,
            ),
        )
    }
    when (downloadReaderEntryAction(volume.readerType, volume.format, existing) { record ->
        files.isVerifiedLocalArtifact(record.localReference, record.expectedBytes)
    }) {
        DownloadReaderEntryAction.OpenPreparation -> {
            openPreparation()
            return
        }
        DownloadReaderEntryAction.ValidateCurrentArtifact,
        DownloadReaderEntryAction.ValidateStreamingAccess,
        -> Unit
    }
    requestAccess(volume.id, true) { outcome ->
        when (outcome) {
            AndroidReaderAccessOutcome.DownloadRequired -> openPreparation()
            else -> {
                val readerIntent = outcome.toNativeReaderIntent(context, profileId, work.id, work.title, volume.id)
                if (readerIntent != null) context.startActivity(readerIntent)
                else outcome.toReaderRoute(volume.id)?.let(onUnavailable)
            }
        }
    }
}

private fun AndroidReaderAccessOutcome.toNativeReaderIntent(
    context: android.content.Context,
    profileId: String,
    workId: String,
    workTitle: String,
    volumeId: String,
): android.content.Intent? {
    val artifact = this as? AndroidReaderAccessOutcome.LocalArtifact ?: return null
    if (!artifact.readerType.equals("reflowable", true) || !artifact.format.equals("EPUB", true)) return null
    return ReaderActivity.createManagedDownloadIntent(
        context = context,
        profileId = profileId,
        workId = workId,
        volumeId = volumeId,
        displayTitle = workTitle,
        localReference = artifact.localReference,
        serverContentFingerprint = artifact.contentFingerprint,
        expectedBytes = artifact.expectedBytes,
    )
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
