package com.ermao.library

import android.content.Context
import android.content.res.Configuration
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.core.content.ContextCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.bootstrap.ErmaoLibraryRoot
import com.ermao.library.bootstrap.LoginFormState
import com.ermao.library.bootstrap.MainActions
import com.ermao.library.bootstrap.MainUiState
import com.ermao.library.features.shell.MainShell
import com.ermao.library.shared.createAndroidContentRepository
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.auth.domain.Authorization
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.auth.domain.SessionIdentity
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.createAndroidPersonalSettingsRepository
import com.ermao.library.shared.createAndroidAdministrativeSettingsRepository
import com.ermao.library.features.me.platform.AndroidXAppLocaleController
import com.ermao.library.ui.theme.WarmPageTheme
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import com.ermao.library.shared.modules.library.BookContentsPage
import com.ermao.library.shared.modules.library.BookContentsQuery
import com.ermao.library.shared.modules.library.BookContentEntry
import com.ermao.library.shared.modules.library.BookDetailQuery
import com.ermao.library.shared.modules.library.BooksQuery
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.HomeSection
import com.ermao.library.shared.modules.library.LibraryPage
import com.ermao.library.shared.modules.library.domain.BookSummary
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.features.shelves.ui.ShelfCatalogScreen
import com.ermao.library.features.library.ui.LibraryScreen
import com.ermao.library.features.library.application.LibraryUiState
import com.ermao.library.features.content.model.WorksFilters
import com.ermao.library.features.shelves.application.ShelfCatalogUiState
import com.ermao.library.features.shelves.application.ShelfLoadState
import com.ermao.library.shared.modules.shelf.ShelfCatalogEntry
import com.ermao.library.shared.modules.shelf.ShelfCatalogPage
import com.ermao.library.shared.modules.shelf.ShelfKind
import com.ermao.library.shared.modules.shelf.ShelfBookPreview

@RunWith(AndroidJUnit4::class)
class AndroidShellSmokeTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun libraryFilterOpensOnlyFromOverflowAndPreservesDraftActions() {
        val application = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as ErmaoLibraryApplication
        val session = authenticatedSession()
        val state = mutableStateOf(LibraryUiState())
        val applied = mutableStateOf(WorksFilters())
        var applications = 0
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                LibraryScreen(
                    state = state.value,
                    repository = application.contentRepository,
                    context = ContentRequestContext(session.profile, session.identity.namespace),
                    onSelectLibrary = {}, onQueryChanged = {}, onClearQuery = {},
                    onSelectSort = {}, onSelectViewMode = {},
                    onOpenFilter = { state.value = state.value.copy(filterDraft = applied.value) },
                    onUpdateFilterDraft = { state.value = state.value.copy(filterDraft = it) },
                    onRemoveReadingFilter = {},
                    onClearFilters = { state.value = state.value.copy(filterDraft = WorksFilters()) },
                    onApplyFilter = {
                        applied.value = requireNotNull(state.value.filterDraft)
                        applications += 1
                        state.value = state.value.copy(filterDraft = null)
                    },
                    onDismissFilter = { state.value = state.value.copy(filterDraft = null) },
                    onOpenWork = {}, onOpenFacet = { _, _ -> }, onRetry = {}, onLoadNextPage = {},
                    onScrollAnchorChanged = { _, _ -> },
                )
            }
        }
        val filterLabel = application.getString(R.string.library_filter_action)
        val unreadLabel = application.getString(R.string.reading_unread)
        composeRule.onNodeWithTag("library-filter").assertDoesNotExist()
        composeRule.onNodeWithText(filterLabel).assertDoesNotExist()
        composeRule.onNodeWithTag("library-more").performClick()
        composeRule.onNodeWithText(filterLabel).performClick()
        composeRule.onNodeWithTag("library-filter-sheet").assertIsDisplayed()
        composeRule.onNodeWithText(filterLabel).assertDoesNotExist()
        composeRule.onNodeWithText(unreadLabel).performClick()
        composeRule.onNodeWithTag("library-filter-cancel").performClick()
        composeRule.runOnIdle { assertEquals(0, applications); assertEquals(WorksFilters(), applied.value) }
        composeRule.onNodeWithTag("library-more").performClick()
        composeRule.onNodeWithText(filterLabel).performClick()
        composeRule.onNodeWithText(unreadLabel).performClick()
        composeRule.onNodeWithTag("library-filter-apply").performClick()
        composeRule.runOnIdle {
            assertEquals(1, applications)
            assertEquals(com.ermao.library.features.content.model.ReadingFilter.Unread, applied.value.reading)
        }
        composeRule.onNodeWithTag("library-more").performClick()
        composeRule.onNodeWithText(filterLabel).performClick()
        composeRule.onNodeWithTag("library-filter-clear").performClick()
        composeRule.onNodeWithTag("library-filter-apply").performClick()
        composeRule.runOnIdle { assertEquals(2, applications); assertEquals(WorksFilters(), applied.value) }
    }

    @Test
    fun shelfRowsForwardEachBooksOwnIdentity() {
        val application = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as ErmaoLibraryApplication
        val session = authenticatedSession()
        val opened = mutableListOf<String>()
        val shelf = ShelfCatalogEntry(
            "shelf-test", "Reading", null, ShelfKind.Static, 2,
            listOf("Alpha", "Beta").map { ShelfBookPreview(it, "Navigation $it", null, "", 0.0) },
            emptyList(), true,
        )
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                ShelfCatalogScreen(
                    state = ShelfCatalogUiState(content = ShelfLoadState.Ready(
                        listOf(shelf), ShelfCatalogPage(shelf, emptyList(), 1, 1),
                    )),
                    isRoot = false, repository = CatalogNavigationRepository(application.contentRepository),
                    context = ContentRequestContext(session.profile, session.identity.namespace),
                    onSearch = {}, onScope = {}, onRefresh = {}, onLoadMore = {}, onBack = {},
                    onOpenShelf = {}, onOpenBook = { opened.add(it) }, onCreate = { _, _ -> }, onClearSaveError = {},
                )
            }
        }
        composeRule.onNodeWithText("Navigation Alpha").performClick()
        composeRule.onNodeWithText("Navigation Beta").performClick()
        composeRule.runOnIdle { assertEquals(listOf("Alpha", "Beta"), opened) }
    }

    @Test
    fun differentBooksAndSourceTabsNeverReuseThePreviousBookDetail() {
        val application = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as ErmaoLibraryApplication
        val repository = CatalogNavigationRepository(application.contentRepository)
        val backLabel = application.getString(R.string.navigate_back)
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                MainShell(
                    session = authenticatedSession(), contentRepository = repository,
                    personalSettingsRepository = createAndroidPersonalSettingsRepository(application),
                    administrativeSettingsRepository = createAndroidAdministrativeSettingsRepository(application),
                    workManagementRepository = application.workManagementRepository,
                    downloadCatalog = application.downloadCatalog, downloadFiles = application.downloadFiles,
                    sharedDownloadCatalog = application.sharedDownloadCatalog,
                    localeController = AndroidXAppLocaleController(), onSessionUnauthorized = {},
                    onRefreshSession = {}, onPurgeCurrentNamespace = {}, onLogout = {},
                )
            }
        }
        composeRule.onNodeWithTag("tab-select-library").performClick()
        listOf("Alpha", "Beta", "Alpha").forEach { name ->
            composeRule.onNodeWithText("Navigation $name").performClick()
            composeRule.onNode(hasText("Author $name") and hasAnyAncestor(hasTestTag("work-detail")))
                .assertIsDisplayed()
            composeRule.onNodeWithContentDescription(backLabel).performClick()
            composeRule.onNodeWithTag("library-works-grid").assertIsDisplayed()
        }
        composeRule.onNodeWithText("Navigation Beta").performClick()
        composeRule.onNodeWithTag("tab-select-home").performClick()
        composeRule.onNodeWithText("Navigation Alpha").performClick()
        composeRule.onNode(hasText("Author Alpha") and hasAnyAncestor(hasTestTag("work-detail"))).assertIsDisplayed()
        composeRule.onNodeWithTag("tab-select-library").performClick()
        composeRule.onNode(hasText("Author Beta") and hasAnyAncestor(hasTestTag("work-detail"))).assertIsDisplayed()
    }

    @Test
    fun noProfileShowsInlineServerAndLoginFields() {
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                ErmaoLibraryRoot(
                    state = MainUiState(session = AppSession.NoServer),
                    actions = noOpMainActions,
                    contentRepository = createAndroidContentRepository(InstrumentationRegistry.getInstrumentation().targetContext),
                )
            }
        }

        composeRule.onNodeWithTag("login-server-address").assertIsDisplayed()
        composeRule.onNodeWithTag("login-submit").assertIsDisplayed()
        composeRule.onAllNodesWithTag("login-entry-close").assertCountEquals(0)
    }

    @Test
    fun loginCheckKeepsVisibleIndeterminateFeedbackAndPreventsAnotherSubmission() {
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                ErmaoLibraryRoot(
                    state = MainUiState(
                        session = AppSession.CheckingServer(
                            ServerConnectionDraft("127.0.0.1", "http://127.0.0.1:3000"),
                        ),
                        loginForm = LoginFormState(
                            serverAddress = "http://127.0.0.1:3000",
                            email = "reader@example.com",
                            password = "password",
                        ),
                        operationInProgress = true,
                    ),
                    actions = noOpMainActions,
                    contentRepository = createAndroidContentRepository(
                        InstrumentationRegistry.getInstrumentation().targetContext,
                    ),
                )
            }
        }

        composeRule.onNodeWithTag("login-submit").assertIsDisplayed().assertIsNotEnabled()
        composeRule.onNodeWithTag("primary-action-loading").assertIsDisplayed()
    }

    @Test
    fun startupServerProbeLeavesTheLoginFormUsable() {
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                ErmaoLibraryRoot(
                    state = MainUiState(
                        session = AppSession.CheckingServer(
                            ServerConnectionDraft("127.0.0.1", "http://127.0.0.1:3000"),
                        ),
                        loginForm = LoginFormState(
                            serverAddress = "http://127.0.0.1:3000",
                            email = "reader@example.com",
                            password = "password",
                        ),
                    ),
                    actions = noOpMainActions,
                    contentRepository = createAndroidContentRepository(
                        InstrumentationRegistry.getInstrumentation().targetContext,
                    ),
                )
            }
        }

        composeRule.onNodeWithTag("login-submit").assertIsDisplayed().assertIsEnabled()
    }

    @Test
    fun authenticatedServerManagementReusesLoginEntryAndCanReturnToShell() {
        val session = authenticatedSession()
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                ErmaoLibraryRoot(
                    state = MainUiState(
                        session = session,
                        serverProfiles = listOf(session.profile.toSnapshot()),
                        showServerCenter = true,
                    ),
                    actions = noOpMainActions,
                    contentRepository = createAndroidContentRepository(InstrumentationRegistry.getInstrumentation().targetContext),
                )
            }
        }

        composeRule.onNodeWithTag("login-server-address").assertIsDisplayed()
        composeRule.onNodeWithTag("login-entry-close").assertIsDisplayed()
    }

    @Test
    fun eachRootTabOwnsAVisibleNavigationDestination() {
        val application = InstrumentationRegistry.getInstrumentation()
            .targetContext
            .applicationContext as ErmaoLibraryApplication
        composeRule.setContent {
            WarmPageTheme(darkTheme = false) {
                MainShell(
                    session = authenticatedSession(),
                    contentRepository = application.contentRepository,
                    personalSettingsRepository = createAndroidPersonalSettingsRepository(
                        InstrumentationRegistry.getInstrumentation().targetContext,
                    ),
                    administrativeSettingsRepository = createAndroidAdministrativeSettingsRepository(
                        InstrumentationRegistry.getInstrumentation().targetContext,
                    ),
                    workManagementRepository = application.workManagementRepository,
                    downloadCatalog = application.downloadCatalog,
                    downloadFiles = application.downloadFiles,
                    sharedDownloadCatalog = application.sharedDownloadCatalog,
                    localeController = AndroidXAppLocaleController(),
                    onSessionUnauthorized = {},
                    onRefreshSession = {},
                    onPurgeCurrentNamespace = {},
                    onLogout = {},
                )
            }
        }

        composeRule.onNodeWithTag("tab-home").assertIsDisplayed()
        listOf(
            "library",
            "shelves",
            "me",
            "home",
        ).forEach { tab ->
            composeRule.onNodeWithTag("tab-select-$tab").performClick()
            composeRule.onNodeWithTag(if (tab == "shelves") "shelves-root" else "tab-$tab").assertIsDisplayed()
        }
    }

    @Test
    fun lightDarkAndSupportedLocalesResolveFromResources() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val lightContext = context.withNightMode(Configuration.UI_MODE_NIGHT_NO)
        val darkContext = context.withNightMode(Configuration.UI_MODE_NIGHT_YES)
        val englishContext = context.withLocale(Locale.forLanguageTag("en-US"))
        val chineseContext = context.withLocale(Locale.forLanguageTag("zh-CN"))

        assertNotEquals(
            ContextCompat.getColor(lightContext, R.color.window_background),
            ContextCompat.getColor(darkContext, R.color.window_background),
        )
        assertEquals("Home", englishContext.getString(R.string.tab_home))
        assertEquals("首页", chineseContext.getString(R.string.tab_home))
    }
}

/** Only catalog reads are replaced; the real Shell and native detail stacks run unchanged. */
private class CatalogNavigationRepository(delegate: ContentRepository) : ContentRepository by delegate {
    private val books = listOf("Alpha", "Beta").map { BookSummary(it, "Navigation $it", "Author $it", "", 0.0) }

    override suspend fun loadHome(context: ContentRequestContext): ContentResult<HomeSnapshot> = ContentResult.Content(
        HomeSnapshot(HomeSection.Content(null), HomeSection.Content(emptyList()), HomeSection.Content(books)),
    )

    override suspend fun loadBooks(context: ContentRequestContext, query: BooksQuery): ContentResult<LibraryPage<BookSummary>> =
        ContentResult.Content(LibraryPage(books, 1, 24, books.size, 1))

    override suspend fun loadBookDetail(context: ContentRequestContext, query: BookDetailQuery): ContentResult<BookDetailSummary> {
        val book = books.single { it.id == query.bookId }
        return ContentResult.Content(BookDetailSummary(
            id = book.id, sourceNodeId = "node-${book.id}", title = book.title, author = book.author,
            description = null, tags = emptyList(), seriesName = null, seriesIndex = null,
            coverStatus = "MISSING", coverUrl = "", continueResourceId = null,
            continueResourceProgress = 0.0, completed = false, resources = emptyList(),
        ))
    }

    override suspend fun loadBookContents(context: ContentRequestContext, query: BookContentsQuery): ContentResult<BookContentsPage> {
        val node = BookContentEntry(
            sourceNodeId = "node-${query.bookId}", parentSourceNodeId = null,
            name = query.bookId, title = "Navigation ${query.bookId}", description = null,
            kind = "FOLDER", physicalKind = "DIRECTORY", sizeBytes = null,
            observedAt = "2026-08-27T00:00:00Z", hasChildren = false,
            resourceId = null, representativeResourceId = null, coverUrl = null,
        )
        return ContentResult.Content(BookContentsPage(
            query.bookId, node.sourceNodeId, null, node, emptyList(), null, emptyList(), emptyList(), 1, 100, 0, 1,
        ))
    }
}

private val noOpMainActions = MainActions(
    onOpenServerCenter = {},
    onCloseServerCenter = {},
    onLoginEmailChanged = {},
    onLoginPasswordChanged = {},
    onLoginServerAddressChanged = {},
    onLogin = {},
    onLoginEntry = {},
    onSelectLoginServer = {},
    onDeleteLoginServer = {},
    onAcceptLoginUnsafeTls = {},
    onDismissOperationError = {},
    onSetupNameChanged = {},
    onSetupEmailChanged = {},
    onSetupPasswordChanged = {},
    onSetupConfirmationChanged = {},
    onSetup = {},
    onRetrySession = {},
    onRequireReauthentication = {},
    onRefreshSessionAwaiting = {},
    onPurgeCurrentNamespace = {},
    onLogoutAwaiting = {},
    onLogout = {},
)

private fun authenticatedSession(): AppSession.Authenticated {
    val parsed = ServerBaseUrl.parse("https://books.example.com")
    check(parsed is ServerBaseUrlParseResult.Valid)
    val profile = ServerProfile(
        id = "profile-test",
        displayName = "Home Library",
        baseUrl = parsed.baseUrl,
        serverIdentity = "server-test",
        isActive = true,
        tlsMode = TlsMode.SystemTrust,
    )
    val identity = SessionIdentity(
        userId = "user-test",
        email = "reader@example.com",
        displayName = "Reader",
        namespace = PrivateDataNamespace("server-test", "user-test", 1),
    )
    return AppSession.Authenticated(
        profile,
        identity,
        Authorization(false, false, true, emptySet(), false, 1),
    )
}

private fun Context.withLocale(locale: Locale): Context = createConfigurationContext(
    Configuration(resources.configuration).apply { setLocale(locale) },
)

private fun ServerProfile.toSnapshot() = com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot(
    id = id,
    displayName = displayName,
    baseUrl = baseUrl.value,
    serverIdentity = serverIdentity,
    isActive = isActive,
    tlsMode = tlsMode,
)

private fun Context.withNightMode(nightMode: Int): Context = createConfigurationContext(
    Configuration(resources.configuration).apply {
        uiMode = (uiMode and Configuration.UI_MODE_NIGHT_MASK.inv()) or nightMode
    },
)
