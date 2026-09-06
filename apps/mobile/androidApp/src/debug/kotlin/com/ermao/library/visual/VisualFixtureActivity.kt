package com.ermao.library.visual

import android.app.Activity
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.core.graphics.createBitmap
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.ContentSort
import com.ermao.library.features.content.model.ContentViewMode
import com.ermao.library.features.content.model.ContinueReadingCard
import com.ermao.library.features.content.model.HomeContent
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.content.model.AssetContent
import com.ermao.library.features.content.model.ReadingFilter
import com.ermao.library.features.content.model.ReadingUnitContent
import com.ermao.library.features.content.model.WorksFilters
import com.ermao.library.features.home.application.HomeUiState
import com.ermao.library.features.home.ui.HomeScreen
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.library.application.LibraryUiState
import com.ermao.library.features.library.application.ScopeUiState
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.features.library.ui.LibraryScreen
import com.ermao.library.features.library.ui.WorkDetailScreen
import com.ermao.library.features.workmanagement.BookManagementHost
import com.ermao.library.features.workmanagement.application.WorkManagementViewModel
import com.ermao.library.platform.persistence.AndroidCoverCache
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.AuthenticatedCover
import com.ermao.library.shared.modules.library.BookContentEntry
import com.ermao.library.shared.modules.library.BookContentsPage
import com.ermao.library.shared.modules.library.BookDetailPresentation
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.FacetPage
import com.ermao.library.shared.modules.library.FacetQuery
import com.ermao.library.shared.modules.library.GroupingQuery
import com.ermao.library.shared.modules.library.GroupingSummary
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.LibraryPage
import com.ermao.library.shared.modules.library.BookDetailQuery
import com.ermao.library.shared.modules.library.BooksQuery
import com.ermao.library.shared.modules.library.domain.BookDetailSummary
import com.ermao.library.shared.modules.library.domain.BookSummary
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.shelf.domain.ShelfKind
import com.ermao.library.shared.modules.shelf.domain.ShelfSummary
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookDeletionOutcome
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.CoverMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.ManagementFieldValue
import com.ermao.library.shared.modules.workmanagement.domain.ManagementSnapshot
import com.ermao.library.shared.modules.workmanagement.domain.ManagementTarget
import com.ermao.library.shared.modules.workmanagement.domain.MetadataApplyOutcome
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult
import com.ermao.library.shared.modules.workmanagement.domain.RecognizedField
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import com.ermao.library.ui.theme.WarmPageTheme
import androidx.lifecycle.viewmodel.compose.viewModel
import java.io.ByteArrayOutputStream
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.runBlocking

/**
 * Debug-only, no-network host for stable Android visual-regression captures.
 *
 * Launchers must use [VisualFixtureContract.intent] so every capture names the
 * rendered scenario explicitly. Unknown or missing values fail closed instead
 * of silently producing a misleading baseline.
 */
class VisualFixtureActivity : ComponentActivity() {
    private val fixtureManagementRepository = FixtureManagementRepository()

    var renderedVariant: VisualFixtureVariant? by mutableStateOf(null)
        private set

    @Volatile
    var isCaptureReady: Boolean = false
        private set

    override fun onCreate(savedInstanceState: Bundle?) {
        val variant = VisualFixtureContract.variantFrom(intent)
        val fontScale = intent.getFloatExtra(VisualFixtureContract.EXTRA_FONT_SCALE, 1f)
        // A fixture launch is a new golden sample, never a continuation of the
        // previous scenario's scroll or modal state.
        super.onCreate(null)
        if (variant == null) {
            setResult(Activity.RESULT_CANCELED)
            finish()
            return
        }

        val systemBarPolicy = visualFixtureSystemBarPolicy(variant.appearance)
        val fixtureSystemBarStyle = if (systemBarPolicy.useDarkForeground) {
            SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
        } else {
            SystemBarStyle.dark(Color.TRANSPARENT)
        }
        enableEdgeToEdge(
            statusBarStyle = fixtureSystemBarStyle,
            navigationBarStyle = fixtureSystemBarStyle,
        )
        applySystemBarPolicy(systemBarPolicy)
        renderedVariant = variant
        prewarmFixtureCovers(variant.scenario)
        setContent {
            val baseContext = LocalContext.current
            val baseConfiguration = LocalConfiguration.current
            val fixtureConfiguration = remember(variant, fontScale, baseConfiguration) {
                variant.overrideConfiguration(baseConfiguration, fontScale)
            }
            val fixtureContext = remember(baseContext, fixtureConfiguration) {
                baseContext.createConfigurationContext(fixtureConfiguration)
            }
            // Activity.intent is assigned after attachBaseContext on API 31, so
            // the deterministic fixture locale/font scale must be scoped to the
            // composition instead of mutating the Activity resources lifecycle.
            CompositionLocalProvider(
                androidx.activity.compose.LocalActivityResultRegistryOwner provides this@VisualFixtureActivity,
                LocalContext provides fixtureContext,
                LocalConfiguration provides fixtureConfiguration,
                androidx.compose.ui.platform.LocalResources provides fixtureContext.resources,
                LocalDensity provides Density(
                    density = fixtureContext.resources.displayMetrics.density,
                    fontScale = fontScale,
                ),
            ) {
                WarmPageTheme(darkTheme = variant.appearance == VisualFixtureAppearance.Dark) {
                    when (variant.scenario) {
                        VisualFixtureScenario.HomeDefault -> FixtureHome()
                        VisualFixtureScenario.LibraryBooks -> FixtureLibrary(showFilter = false)
                        VisualFixtureScenario.LibraryFilter -> FixtureLibrary(showFilter = true)
                        VisualFixtureScenario.BookAbout -> FixtureBookDetail(
                            managementRepository = fixtureManagementRepository,
                            content = fixtureDetail,
                        )
                        VisualFixtureScenario.BookResources -> FixtureBookDetail(
                            managementRepository = fixtureManagementRepository,
                            content = fixtureDetail.copy(description = null, continueResourceId = "resource-2"),
                            presentation = BookDetailPresentation.ContentBrowser,
                            contents = fixtureContents(fixtureDetail),
                        )
                        VisualFixtureScenario.BookSingleEbook -> FixtureBookDetail(
                            managementRepository = fixtureManagementRepository,
                            content = fixtureSingleEbookDetail,
                        )
                        VisualFixtureScenario.BookActions -> FixtureBookDetail(
                            managementRepository = fixtureManagementRepository,
                            content = fixtureDetail,
                        )
                    }
                }
            }
        }
        markCaptureReadyAfterFrames()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            renderedVariant?.appearance
                ?.let(::visualFixtureSystemBarPolicy)
                ?.let(::applySystemBarPolicy)
        }
    }

    private fun applySystemBarPolicy(policy: VisualFixtureSystemBarPolicy) {
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = policy.useDarkForeground
            isAppearanceLightNavigationBars = policy.useDarkForeground
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_DEFAULT
            if (policy.visible) {
                show(WindowInsetsCompat.Type.systemBars())
            }
        }
    }

    private fun prewarmFixtureCovers(scenario: VisualFixtureScenario) {
        val paths = when (scenario) {
            VisualFixtureScenario.HomeDefault,
            VisualFixtureScenario.LibraryBooks,
            VisualFixtureScenario.LibraryFilter,
            -> fixtureBooks.map(BookCard::coverUrl)
            VisualFixtureScenario.BookAbout,
            VisualFixtureScenario.BookResources,
            VisualFixtureScenario.BookActions,
            -> fixtureBooks.map(BookCard::coverUrl) + fixtureDetail.coverPaths()
            VisualFixtureScenario.BookSingleEbook -> fixtureBooks.map(BookCard::coverUrl) +
                fixtureSingleEbookDetail.coverPaths()
        }.distinct()
        runBlocking(Dispatchers.IO) {
            // Replace-install intentionally preserves app data. Clear this
            // debug-only namespace before every fixture launch so a changed
            // cover renderer can never reuse pixels from an older APK.
            AndroidCoverCache.clearNamespace(applicationContext, fixtureRequestContext)
            paths.forEach { path ->
                AndroidCoverCache.load(applicationContext, fixtureRequestContext, path, fixtureRepository)
            }
        }
    }

    private fun markCaptureReadyAfterFrames(remainingFrames: Int = CAPTURE_SETTLE_FRAMES) {
        window.decorView.postOnAnimation {
            if (remainingFrames <= 1) {
                isCaptureReady = true
            } else {
                markCaptureReadyAfterFrames(remainingFrames - 1)
            }
        }
    }
}

enum class VisualFixtureScenario(val wireValue: String) {
    HomeDefault("home-default"),
    LibraryBooks("library-books"),
    LibraryFilter("library-filter"),
    BookAbout("book-about"),
    BookResources("book-resources"),
    BookSingleEbook("book-single-ebook"),
    BookActions("book-actions"),
    ;

    companion object {
        fun fromWireValue(value: String?): VisualFixtureScenario? = entries.firstOrNull { it.wireValue == value }
    }
}

enum class VisualFixtureLocale(val wireValue: String, val languageTag: String) {
    ZhCn("zh-CN", "zh-CN"),
    EnUs("en-US", "en-US"),
    ;

    companion object {
        fun fromWireValue(value: String?): VisualFixtureLocale? = entries.firstOrNull { it.wireValue == value }
    }
}

enum class VisualFixtureAppearance(val wireValue: String) {
    Light("light"),
    Dark("dark"),
    ;

    companion object {
        fun fromWireValue(value: String?): VisualFixtureAppearance? = entries.firstOrNull { it.wireValue == value }
    }
}

data class VisualFixtureVariant(
    val scenario: VisualFixtureScenario,
    val locale: VisualFixtureLocale,
    val appearance: VisualFixtureAppearance,
) {
    val outputName: String
        get() = "${scenario.wireValue}-${locale.wireValue}-${appearance.wireValue}.png"

    // Debug fixtures package both locales in one APK and never ship as an app bundle.
    @SuppressLint("AppBundleLocaleChanges")
    fun overrideConfiguration(base: Configuration, fontScale: Float): Configuration = Configuration(base).apply {
        setLocale(Locale.forLanguageTag(this@VisualFixtureVariant.locale.languageTag))
        val nightMode = when (appearance) {
            VisualFixtureAppearance.Light -> Configuration.UI_MODE_NIGHT_NO
            VisualFixtureAppearance.Dark -> Configuration.UI_MODE_NIGHT_YES
        }
        uiMode = (uiMode and Configuration.UI_MODE_NIGHT_MASK.inv()) or nightMode
        this.fontScale = fontScale
    }
}

object VisualFixtureContract {
    const val EXTRA_SCENARIO = "com.ermao.library.visual.extra.SCENARIO"
    const val EXTRA_LOCALE = "com.ermao.library.visual.extra.LOCALE"
    const val EXTRA_APPEARANCE = "com.ermao.library.visual.extra.APPEARANCE"
    const val EXTRA_FONT_SCALE = "com.ermao.library.visual.extra.FONT_SCALE"

    fun intent(context: Context, variant: VisualFixtureVariant): Intent =
        Intent(context, VisualFixtureActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION)
            .putExtra(EXTRA_SCENARIO, variant.scenario.wireValue)
            .putExtra(EXTRA_LOCALE, variant.locale.wireValue)
            .putExtra(EXTRA_APPEARANCE, variant.appearance.wireValue)

    fun scenarioFrom(intent: Intent): VisualFixtureScenario? =
        VisualFixtureScenario.fromWireValue(intent.getStringExtra(EXTRA_SCENARIO))

    fun variantFrom(intent: Intent): VisualFixtureVariant? {
        val scenario = scenarioFrom(intent) ?: return null
        val locale = VisualFixtureLocale.fromWireValue(intent.getStringExtra(EXTRA_LOCALE)) ?: return null
        val appearance = VisualFixtureAppearance.fromWireValue(intent.getStringExtra(EXTRA_APPEARANCE)) ?: return null
        return VisualFixtureVariant(scenario, locale, appearance)
    }
}

@androidx.compose.runtime.Composable
private fun FixtureHome() {
    HomeScreen(
        state = HomeUiState(
            isLoading = false,
            content = HomeContent(
                continueReading = ContinueReadingCard(
                    book = fixtureBooks.first(),
                    resourceTitle = "第二卷 黑暗森林",
                    positionLabel = "第二章 黑暗森林",
                    lastReadAtEpochMillis = Instant.parse("2026-08-15T01:18:00Z").toEpochMilli(),
                ),
                recentReading = fixtureBooks.take(3),
                recentAdded = fixtureBooks.drop(3).take(3),
            ),
        ),
        repository = fixtureRepository,
        context = fixtureRequestContext,
        onOpenBook = {},
        onContinueReading = {},
        onOpenLibrary = {},
        onRetry = {},
        onRefresh = {},
        lastReadClock = VisualFixtureClock,
    )
}

private val VisualFixtureClock: Clock = Clock.fixed(
    Instant.parse("2026-08-15T02:00:00Z"),
    ZoneId.of("Asia/Shanghai"),
)

@androidx.compose.runtime.Composable
private fun FixtureLibrary(showFilter: Boolean) {
    val booksState = ScopeUiState(
        query = "",
        sort = ContentSort.RecentAdded,
        viewMode = ContentViewMode.Grid,
        filters = WorksFilters(
            reading = ReadingFilter.Unread,
        ),
        works = fixtureBooks,
        total = 128,
        loadedPage = 1,
        totalPages = 3,
        isLoading = false,
    )
    LibraryScreen(
        state = LibraryUiState(
            selectedScope = LibraryScope.Books,
            libraryOptions = listOf(
                com.ermao.library.features.library.application.LibrarySourceOption("library-1", "文学"),
                com.ermao.library.features.library.application.LibrarySourceOption("library-2", "漫画"),
            ),
            scopes = LibraryScope.entries.associateWith { scope ->
                if (scope == LibraryScope.Books) booksState else ScopeUiState(isLoading = false)
            },
            filterDraft = WorksFilters(
                reading = ReadingFilter.Unread,
            ).takeIf { showFilter },
        ),
        repository = fixtureRepository,
        context = fixtureRequestContext,
        onSelectLibrary = {},
        onQueryChanged = {},
        onClearQuery = {},
        onSelectSort = {},
        onSelectViewMode = {},
        onOpenFilter = {},
        onUpdateFilterDraft = {},
        onRemoveReadingFilter = {},
        onClearFilters = {},
        onApplyFilter = {},
        onDismissFilter = {},
        onOpenWork = {},
        onOpenFacet = { _, _ -> },
        onRetry = {},
        onLoadNextPage = {},
        onScrollAnchorChanged = { _, _ -> },
    )
}

@androidx.compose.runtime.Composable
private fun FixtureBookDetail(
    managementRepository: FixtureManagementRepository,
    content: BookDetailContent,
    presentation: BookDetailPresentation = BookDetailPresentation.ResourceDetail,
    contents: BookContentsPage? = null,
) {
    var showShelfPicker by remember { mutableStateOf(false) }
    var showMultiDownload by remember { mutableStateOf(false) }
    val bookReadingStatuses by managementRepository.bookReadingStatuses.collectAsState()
    val renderedContent = if (bookReadingStatuses[content.book.id] == ManagedReadingStatus.Finished) {
        content.copy(completed = true)
    } else {
        content
    }
    val selectedResource = renderedContent.resources.getOrNull(1) ?: renderedContent.resources.firstOrNull()
    val selectedResourceId = if (presentation == BookDetailPresentation.ContentBrowser) null else selectedResource?.id
    val multiDownloadRootNodeId = contents?.currentNode?.sourceNodeId
    val multiDownloadChildren = contents?.let { page ->
        mapOf(page.currentNode.sourceNodeId to page.entries)
    }.orEmpty()
    val multiDownloadDescendants = contents?.let { page ->
        mapOf(page.currentNode.sourceNodeId to page.entries.mapNotNull(BookContentEntry::resourceId).toSet())
    }.orEmpty()
    val managementViewModel: WorkManagementViewModel = viewModel(
        factory = WorkManagementViewModel.factory(
            repository = managementRepository,
            context = fixtureRequestContext,
            bookId = content.book.id,
            onUnauthorized = {},
        ),
    )
    BookManagementHost(
        repository = managementRepository,
        context = fixtureRequestContext,
        canManage = true,
        onUnauthorized = {},
        onRefreshAuthorization = {},
        onChanged = {},
        onOpenKindleSettings = {},
        onOpenKindleQueue = {},
    ) {
        WorkDetailScreen(
            state = WorkDetailUiState(
                isLoading = false,
                content = renderedContent,
                selectedResourceId = selectedResourceId,
                presentation = presentation,
                contents = contents,
                shelves = fixtureShelves,
                selectedShelfIds = setOf(fixtureShelves.first().id),
                isShelfPickerVisible = showShelfPicker,
                isMultiDownloadVisible = showMultiDownload,
                multiDownloadRootNodeId = multiDownloadRootNodeId.takeIf { showMultiDownload },
                multiDownloadChildrenByNodeId = multiDownloadChildren.takeIf { showMultiDownload }.orEmpty(),
                multiDownloadDescendantResourceIdsByNodeId = multiDownloadDescendants.takeIf { showMultiDownload }.orEmpty(),
                multiDownloadExpandedNodeIds = setOfNotNull(multiDownloadRootNodeId).takeIf { showMultiDownload }.orEmpty(),
                multiDownloadResources = renderedContent.resources.takeIf { showMultiDownload }.orEmpty(),
            ),
            repository = fixtureRepository,
            context = fixtureRequestContext,
            onBack = {},
            onSelectResource = {},
            onOpenSourceNode = {},
            onSelectContentsSort = {},
            onSelectContentsPage = {},
            onSelectReadingUnitsPage = {},
            onRetrySurface = {},
            onOpenShelfPicker = { showShelfPicker = true },
            onDismissShelfPicker = { showShelfPicker = false },
            onToggleShelf = {},
            onSaveShelves = {},
            onShelfSaveFeedbackShown = {},
            onViewShelves = {},
            onOpenFacet = { _, _ -> },
            onRetry = {},
            onOpenMultiDownload = { showMultiDownload = true },
            onDismissMultiDownload = { showMultiDownload = false },
            onToggleMultiDownloadFolder = {},
            onEnsureMultiDownloadFolderLoaded = {},
            onPerformDownloadBatch = { _, completion -> completion(com.ermao.library.shared.modules.downloads.DownloadBatchResult(emptyList())) },
            managementViewModel = managementViewModel,
            downloadRecordsByResource = selectedResource?.let { resource ->
                mapOf(resource.id to fixtureCompletedDownload(renderedContent, resource))
            }.orEmpty(),
        )
    }
}

private fun fixtureContents(content: BookDetailContent): BookContentsPage {
    val rootSourceNodeId = "fixture-root-${content.book.id}"
    val root = BookContentEntry(
        sourceNodeId = rootSourceNodeId,
        parentSourceNodeId = null,
        name = content.book.title,
        title = content.book.title,
        description = content.description,
        kind = "FOLDER",
        physicalKind = "DIRECTORY",
        sizeBytes = null,
        observedAt = "2026-08-15T00:00:00Z",
        hasChildren = true,
        resourceId = null,
        representativeResourceId = content.resources.firstOrNull()?.id,
        coverUrl = content.book.coverUrl,
    )
    val entries = content.resources.map { resource ->
        BookContentEntry(
            sourceNodeId = "fixture-entry-${resource.id}",
            parentSourceNodeId = rootSourceNodeId,
            name = resource.title,
            title = resource.title,
            description = resource.description,
            kind = "FILE",
            physicalKind = "FILE",
            sizeBytes = resource.sizeBytes,
            observedAt = "2026-08-15T00:00:00Z",
            hasChildren = false,
            resourceId = resource.id,
            representativeResourceId = null,
            coverUrl = resource.coverUrl,
        )
    }
    return BookContentsPage(
        bookId = content.book.id,
        currentSourceNodeId = rootSourceNodeId,
        currentResourceId = null,
        currentNode = root,
        currentResourceIds = entries.mapNotNull(BookContentEntry::resourceId),
        parentSourceNodeId = null,
        breadcrumbs = emptyList(),
        entries = entries,
        page = 1,
        pageSize = entries.size.coerceAtLeast(1),
        total = entries.size,
        totalPages = 1,
    )
}

private fun fixtureCompletedDownload(
    content: BookDetailContent,
    resource: ResourceContent,
): AndroidDownloadRecord = AndroidDownloadRecord(
    taskId = "fixture-download-${resource.id}",
    namespace = AndroidDownloadNamespace("visual-fixture-server", "visual-fixture-user", 1),
    bookId = content.book.id,
    bookTitle = content.book.title,
    author = content.book.author,
    coverUrl = resource.coverUrl,
    resourceId = resource.id,
    resourceTitle = resource.title,
    format = resource.format,
    readerType = resource.readerType,
    assetId = resource.assets.firstOrNull()?.id ?: "asset-${resource.id}",
    sourceApiPath = "/api/resources/${resource.id}/asset",
    sourceMimeType = "application/epub+zip",
    expectedBytes = resource.sizeBytes,
    transferredBytes = resource.sizeBytes,
    status = AndroidDownloadStatus.Completed,
    localReference = "fixture-${resource.id}.epub",
    verified = true,
    createdAtEpochMillis = 1,
    updatedAtEpochMillis = 2,
    resourceIndex = resource.resourceIndex,
    resourceSortOrder = resource.sortOrder,
)

/**
 * The visual fixture exercises the real management host and session. Its
 * menu-only captures must stay offline, so operations behind a selected menu
 * action are deliberately outside this fixture's contract.
 */
private class FixtureManagementRepository : WorkManagementRepository {
    private val mutableBookReadingStatuses = MutableStateFlow<Map<String, ManagedReadingStatus>>(emptyMap())
    val bookReadingStatuses: StateFlow<Map<String, ManagedReadingStatus>> = mutableBookReadingStatuses.asStateFlow()

    override suspend fun loadBookCompleted(
        context: BookManagementContext,
        bookId: String,
    ): WorkManagementResult<Boolean> = WorkManagementResult.Content(
        mutableBookReadingStatuses.value[bookId] == ManagedReadingStatus.Finished,
    )

    override suspend fun saveBookFields(
        context: BookManagementContext,
        bookId: String,
        draft: BookMetadataDraft,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: saveBookFields")

    override suspend fun replaceBookTags(
        context: BookManagementContext,
        bookId: String,
        current: List<String>,
        next: List<String>,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: replaceBookTags")

    override suspend fun loadManagementSnapshot(
        context: BookManagementContext,
        target: ManagementTarget,
    ): WorkManagementResult<ManagementSnapshot> = error("Unexpected visual-fixture operation: loadManagementSnapshot")

    override suspend fun saveResourceFields(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
        fields: List<ManagementFieldValue>,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: saveResourceFields")

    override suspend fun saveSourcePresentation(
        context: BookManagementContext,
        bookId: String,
        sourceNodeId: String,
        title: String,
        description: String,
        removeCover: Boolean,
        upload: CoverUpload?,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: saveSourcePresentation")

    override suspend fun regenerateBookImage(
        context: BookManagementContext,
        bookId: String,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: regenerateBookImage")

    override suspend fun deleteResourceSource(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
        confirmation: String,
        idempotencyKey: String,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: deleteResourceSource")

    override suspend fun applyRecognizedFields(
        context: BookManagementContext,
        target: ManagementTarget,
        candidate: MetadataCandidate,
        fields: List<RecognizedField>,
    ): WorkManagementResult<MetadataApplyOutcome> = error("Unexpected visual-fixture operation: applyRecognizedFields")

    override suspend fun applyDirectoryMetadata(
        context: BookManagementContext,
        bookId: String,
        sourceNodeId: String,
        title: String,
        description: String,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: applyDirectoryMetadata")

    override suspend fun uploadCover(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
        upload: CoverUpload,
    ): WorkManagementResult<CoverMutationOutcome> = error("Unexpected visual-fixture operation: uploadCover")

    override suspend fun regenerateResourceCover(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: regenerateResourceCover")

    override suspend fun rescanBook(
        context: BookManagementContext,
        sourceNodeId: String,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: rescanBook")

    override suspend fun deleteBook(
        context: BookManagementContext,
        bookId: String,
    ): WorkManagementResult<BookDeletionOutcome> = error("Unexpected visual-fixture operation: deleteBook")

    override suspend fun loadMetadataProviders(
        context: BookManagementContext,
    ): WorkManagementResult<List<MetadataProvider>> = error("Unexpected visual-fixture operation: loadMetadataProviders")

    override suspend fun searchMetadata(
        context: BookManagementContext,
        bookId: String,
        sourceNodeId: String,
        providerId: String,
        query: String,
    ): WorkManagementResult<MetadataSearchResult> = error("Unexpected visual-fixture operation: searchMetadata")

    override suspend fun loadKindleSettings(
        context: BookManagementContext,
    ): WorkManagementResult<KindleSettings> = error("Unexpected visual-fixture operation: loadKindleSettings")

    override suspend fun sendToKindle(
        context: BookManagementContext,
        bookId: String,
        assetId: String,
    ): WorkManagementResult<KindleSendOutcome> = error("Unexpected visual-fixture operation: sendToKindle")

    override suspend fun setReadingStatus(
        context: BookManagementContext,
        resourceId: String,
        status: ManagedReadingStatus,
    ): WorkManagementResult<Unit> = error("Unexpected visual-fixture operation: setReadingStatus")

    override suspend fun setBookReadingStatus(
        context: BookManagementContext,
        bookId: String,
        status: ManagedReadingStatus,
    ): WorkManagementResult<Unit> {
        mutableBookReadingStatuses.update { statuses -> statuses + (bookId to status) }
        return WorkManagementResult.Content(Unit)
    }
}

private val fixtureShelves = listOf(
    ShelfSummary(
        id = "shelf-reading-list",
        name = "稍后阅读",
        kind = ShelfKind.Static,
        containsBook = true,
    ),
)

private const val CAPTURE_SETTLE_FRAMES = 30

private val fixtureBooks = listOf(
    fixtureBook("book-1", "三体", "刘慈欣", 34),
    fixtureBook("book-2", "沙丘", "弗兰克·赫伯特", 8),
    fixtureBook("book-3", "人类简史", "尤瓦尔·赫拉利", null),
    fixtureBook("book-4", "银河帝国", "艾萨克·阿西莫夫", null),
    fixtureBook("book-5", "百年孤独", "加西亚·马尔克斯", null),
    fixtureBook("book-6", "活着", "余华", null),
)

private fun fixtureBook(id: String, title: String, author: String, progress: Int?): BookCard = BookCard(
    id = id,
    title = title,
    author = author,
    coverUrl = "fixture://cover/$id",
    progressPercent = progress,
)

private val fixtureDetail = BookDetailContent(
    book = fixtureBooks.first(),
    seriesId = "series-three-body",
    seriesName = "三体系列",
    authorFacetId = "author-liu-cixin",
    description = "在文明与宇宙的尺度上，人类第一次直面来自群星深处的未知回声。",
    tags = listOf("科幻", "长篇小说"),
    resources = listOf(
        fixtureResource("resource-1", "第一卷 地球往事", 100, true),
        fixtureResource("resource-2", "第二卷 黑暗森林", 34, true),
        fixtureResource("resource-3", "第三卷 死神永生", null, true),
        fixtureResource("resource-4", "第四卷 宇宙回声", null, true),
        fixtureResource("comic-1", "漫画版 第一卷", null, true, format = "CBZ", readerType = "comic"),
        fixtureResource("audio-1", "有声版", 12, true, format = "M4B", readerType = "audio"),
    ),
    selectedResourceId = "resource-2",
    readingUnits = listOf(
        ReadingUnitContent("chapter-1", "第一章 科学边界", 100, readingState = ChapterReadingState.Read),
        ReadingUnitContent("chapter-2", "第二章 黑暗森林", 34, readingState = ChapterReadingState.Current),
        ReadingUnitContent("chapter-3", "第三章 遥远回声", readingState = ChapterReadingState.Unread),
    ),
)

private val fixtureSingleEbookDetail = BookDetailContent(
    book = fixtureBooks[1].copy(progressPercent = 42),
    seriesId = "series-dune",
    seriesName = "沙丘系列",
    authorFacetId = "author-frank-herbert",
    description = null,
    tags = listOf("科幻"),
    resources = listOf(fixtureResource("single-ebook-1", "沙丘", 42, true)),
    selectedResourceId = "single-ebook-1",
    readingUnits = listOf(
        ReadingUnitContent("dune-chapter-1", "第一章 厄拉科斯", 100, readingState = ChapterReadingState.Read),
        ReadingUnitContent("dune-chapter-2", "第二章 沙漠之路", 42, readingState = ChapterReadingState.Current),
        ReadingUnitContent("dune-chapter-3", "第三章 香料", readingState = ChapterReadingState.Unread),
    ),
)

private fun BookDetailContent.coverPaths(): List<String> = resources.map(ResourceContent::coverUrl)

private fun fixtureResource(
    id: String,
    title: String,
    progress: Int?,
    readable: Boolean,
    format: String = "EPUB",
    readerType: String = "reflowable",
): ResourceContent = ResourceContent(
    id = id,
    title = title,
    format = format,
    readerType = readerType,
    resourceIndex = id.substringAfterLast('-').toDoubleOrNull(),
    publishedAt = "2010-11-01",
    language = "zh-CN",
    pageCount = 428,
    metadataSource = "内嵌元数据",
    assets = listOf(
        AssetContent(
            id = "asset-$id",
            path = "/library/三体系列/$title.epub",
            sizeBytes = 3_200_000,
            displaySize = "3.2 MB",
        ),
    ),
    coverUrl = "fixture://cover/$id",
    sizeBytes = 3_200_000,
    progressPercent = progress,
    readable = readable,
    selected = id == "resource-2",
)

private val fixtureRequestContext: ContentRequestContext = run {
    val parsed = ServerBaseUrl.parse("https://visual-fixture.invalid")
    require(parsed is ServerBaseUrlParseResult.Valid)
    ContentRequestContext(
        profile = ServerProfile(
            id = "visual-fixture-profile",
            displayName = "Visual Fixture",
            baseUrl = parsed.baseUrl,
            serverIdentity = "visual-fixture-server",
            isActive = true,
            tlsMode = TlsMode.SystemTrust,
        ),
        namespace = PrivateDataNamespace("visual-fixture-server", "visual-fixture-user", 1),
    )
}

private val fixtureRepository: ContentRepository = object : ContentRepository {
    override suspend fun loadCover(
        context: ContentRequestContext,
        apiPath: String,
        etag: String?,
    ): ContentResult<AuthenticatedCover> = ContentResult.Content(
        value = AuthenticatedCover(
            bytes = fixtureCoverPng(apiPath),
            mimeType = "image/png",
            etag = "fixture-${apiPath.hashCode()}",
        ),
    )

    override suspend fun loadHome(context: ContentRequestContext): ContentResult<HomeSnapshot> = forbidden("loadHome")
    override suspend fun loadContinueReading(context: ContentRequestContext) = forbidden("loadContinueReading")
    override suspend fun loadRecentReading(context: ContentRequestContext, limit: Int) = forbidden("loadRecentReading")
    override suspend fun loadRecentAdded(context: ContentRequestContext, limit: Int) = forbidden("loadRecentAdded")
    override suspend fun loadBooks(context: ContentRequestContext, query: BooksQuery): ContentResult<LibraryPage<BookSummary>> = forbidden("loadBooks")
    override suspend fun loadGroupings(context: ContentRequestContext, query: GroupingQuery): ContentResult<LibraryPage<GroupingSummary>> = forbidden("loadGroupings")
    override suspend fun loadFacet(context: ContentRequestContext, query: FacetQuery): ContentResult<FacetPage> = forbidden("loadFacet")
    override suspend fun loadBookDetail(context: ContentRequestContext, query: BookDetailQuery): ContentResult<BookDetailSummary> = forbidden("loadBookDetail")
    override suspend fun invalidate(namespace: PrivateDataNamespace) = Unit
}

private fun fixtureCoverPng(key: String): ByteArray {
    val palette = intArrayOf(
        Color.rgb(24, 31, 34),
        Color.rgb(108, 52, 25),
        Color.rgb(174, 145, 101),
        Color.rgb(25, 49, 67),
        Color.rgb(71, 52, 31),
        Color.rgb(86, 91, 70),
    )
    val color = palette[(key.hashCode() and Int.MAX_VALUE) % palette.size]
    val bitmap = createBitmap(400, 600)
    val canvas = Canvas(bitmap)
    val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    canvas.drawColor(color)
    paint.color = Color.argb(150, 255, 235, 201)
    paint.strokeWidth = 8f
    paint.style = Paint.Style.STROKE
    canvas.drawCircle(310f, 115f, 210f, paint)
    paint.style = Paint.Style.FILL
    paint.color = Color.argb(190, 12, 15, 18)
    canvas.drawRect(0f, 500f, 400f, 600f, paint)
    return ByteArrayOutputStream().use { output ->
        check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, output))
        bitmap.recycle()
        output.toByteArray()
    }
}

private fun forbidden(operation: String): Nothing = throw AssertionError(
    "Visual fixture attempted non-cover repository operation: $operation",
)
