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
import com.ermao.library.features.content.model.ContentFreshness
import com.ermao.library.features.content.model.ContentSort
import com.ermao.library.features.content.model.ContentViewMode
import com.ermao.library.features.content.model.ContinueReadingCard
import com.ermao.library.features.content.model.HomeContent
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.MediaContent
import com.ermao.library.features.content.model.MediaFilter
import com.ermao.library.features.content.model.ReadingFilter
import com.ermao.library.features.content.model.ReadingUnitContent
import com.ermao.library.features.content.model.VolumeContent
import com.ermao.library.features.content.model.VolumeFileContent
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.model.WorkDetailContent
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
import com.ermao.library.platform.persistence.AndroidCoverCache
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.AuthenticatedCover
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.FacetPage
import com.ermao.library.shared.modules.library.FacetQuery
import com.ermao.library.shared.modules.library.GroupingQuery
import com.ermao.library.shared.modules.library.GroupingSummary
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.LibraryPage
import com.ermao.library.shared.modules.library.OfflineFilterAvailability
import com.ermao.library.shared.modules.library.WorkDetailQuery
import com.ermao.library.shared.modules.library.WorksQuery
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.shelf.domain.ShelfKind
import com.ermao.library.shared.modules.shelf.domain.ShelfSummary
import com.ermao.library.ui.theme.WarmPageTheme
import java.io.ByteArrayOutputStream
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking

/**
 * Debug-only, no-network host for stable Android visual-regression captures.
 *
 * Launchers must use [VisualFixtureContract.intent] so every capture names the
 * rendered scenario explicitly. Unknown or missing values fail closed instead
 * of silently producing a misleading baseline.
 */
class VisualFixtureActivity : ComponentActivity() {
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
                LocalContext provides fixtureContext,
                LocalConfiguration provides fixtureConfiguration,
                LocalDensity provides Density(
                    density = fixtureContext.resources.displayMetrics.density,
                    fontScale = fontScale,
                ),
            ) {
                WarmPageTheme(darkTheme = variant.appearance == VisualFixtureAppearance.Dark) {
                    when (variant.scenario) {
                        VisualFixtureScenario.HomeDefault -> FixtureHome()
                        VisualFixtureScenario.LibraryWorks -> FixtureLibrary(showFilter = false)
                        VisualFixtureScenario.LibraryFilter -> FixtureLibrary(showFilter = true)
                        VisualFixtureScenario.WorkAbout -> FixtureWorkDetail(fixtureDetail)
                        VisualFixtureScenario.WorkVolumes -> FixtureWorkDetail(
                            fixtureDetail.copy(description = null),
                        )
                        VisualFixtureScenario.WorkSingleEbook -> FixtureWorkDetail(fixtureSingleEbookDetail)
                        VisualFixtureScenario.WorkActions -> FixtureWorkDetail(fixtureDetail)
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
            VisualFixtureScenario.LibraryWorks,
            VisualFixtureScenario.LibraryFilter,
            -> fixtureWorks.map(WorkCard::coverUrl)
            VisualFixtureScenario.WorkAbout,
            VisualFixtureScenario.WorkVolumes,
            VisualFixtureScenario.WorkActions,
            -> fixtureWorks.map(WorkCard::coverUrl) + fixtureDetail.coverPaths()
            VisualFixtureScenario.WorkSingleEbook -> fixtureWorks.map(WorkCard::coverUrl) +
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
    LibraryWorks("library-works"),
    LibraryFilter("library-filter"),
    WorkAbout("work-about"),
    WorkVolumes("work-volumes"),
    WorkSingleEbook("work-single-ebook"),
    WorkActions("work-actions"),
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
                    work = fixtureWorks.first(),
                    volumeTitle = "第二卷 黑暗森林",
                    positionLabel = "第二章 黑暗森林",
                    lastReadAtEpochMillis = Instant.parse("2026-08-15T01:18:00Z").toEpochMilli(),
                ),
                recentReading = fixtureWorks.take(3),
                recentAdded = fixtureWorks.drop(3).take(3),
            ),
            freshness = ContentFreshness.Fresh,
        ),
        repository = fixtureRepository,
        context = fixtureRequestContext,
        onOpenWork = {},
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
    val worksState = ScopeUiState(
        query = "",
        sort = ContentSort.RecentAdded,
        viewMode = ContentViewMode.Grid,
        filters = WorksFilters(
            media = setOf(MediaFilter.Ebook),
            reading = setOf(ReadingFilter.Unread),
        ),
        works = fixtureWorks,
        total = 128,
        loadedPage = 1,
        totalPages = 3,
        isLoading = false,
        freshness = ContentFreshness.Fresh,
    )
    LibraryScreen(
        state = LibraryUiState(
            selectedScope = LibraryScope.Works,
            scopes = LibraryScope.entries.associateWith { scope ->
                if (scope == LibraryScope.Works) worksState else ScopeUiState(isLoading = false)
            },
            offlineFilterAvailability = OfflineFilterAvailability.Available,
            filterDraft = WorksFilters(
                media = setOf(MediaFilter.Ebook, MediaFilter.Audiobook),
                reading = setOf(ReadingFilter.Unread),
                downloadedOnly = true,
            ).takeIf { showFilter },
        ),
        repository = fixtureRepository,
        context = fixtureRequestContext,
        onSelectScope = {},
        onQueryChanged = {},
        onClearQuery = {},
        onSelectSort = {},
        onSelectViewMode = {},
        onOpenFilter = {},
        onUpdateFilterDraft = {},
        onRemoveMediaFilter = {},
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
private fun FixtureWorkDetail(content: WorkDetailContent) {
    var showShelfPicker by remember { mutableStateOf(false) }
    val selectedVolume = content.media.firstOrNull()?.volumes?.getOrNull(1)
        ?: content.media.firstOrNull()?.volumes?.firstOrNull()
    WorkDetailScreen(
        state = WorkDetailUiState(
            isLoading = false,
            content = content,
            selectedMediaKind = "EBOOK",
            selectedVolumeId = selectedVolume?.id,
            shelves = fixtureShelves,
            selectedShelfIds = setOf(fixtureShelves.first().id),
            isShelfPickerVisible = showShelfPicker,
        ),
        repository = fixtureRepository,
        context = fixtureRequestContext,
        onBack = {},
        onSelectMedia = {},
        onSelectVolume = {},
        onOpenShelfPicker = { showShelfPicker = true },
        onDismissShelfPicker = { showShelfPicker = false },
        onToggleShelf = {},
        onSaveShelves = {},
        onShelfSaveFeedbackShown = {},
        onViewShelves = {},
        onOpenFacet = { _, _ -> },
        onRetry = {},
        downloadRecordsByVolume = selectedVolume?.let { volume ->
            mapOf(volume.id to fixtureCompletedDownload(content, volume))
        }.orEmpty(),
    )
}

private fun fixtureCompletedDownload(
    content: WorkDetailContent,
    volume: VolumeContent,
): AndroidDownloadRecord = AndroidDownloadRecord(
    taskId = "fixture-download-${volume.id}",
    namespace = AndroidDownloadNamespace("visual-fixture-server", "visual-fixture-user", 1),
    workId = content.work.id,
    workTitle = content.work.title,
    author = content.work.author,
    coverUrl = volume.coverUrl,
    volumeId = volume.id,
    volumeTitle = volume.title,
    format = volume.format,
    readerType = volume.readerType,
    sourceApiPath = "/api/volumes/${volume.id}/file",
    sourceMimeType = "application/epub+zip",
    expectedBytes = volume.sizeBytes,
    transferredBytes = volume.sizeBytes,
    status = AndroidDownloadStatus.Completed,
    localReference = "fixture-${volume.id}.epub",
    verified = true,
    createdAtEpochMillis = 1,
    updatedAtEpochMillis = 2,
)

private val fixtureShelves = listOf(
    ShelfSummary(
        id = "shelf-reading-list",
        name = "稍后阅读",
        kind = ShelfKind.Static,
        containsWork = true,
    ),
)

private const val CAPTURE_SETTLE_FRAMES = 30

private val fixtureWorks = listOf(
    fixtureWork("work-1", "三体", "刘慈欣", 34),
    fixtureWork("work-2", "沙丘", "弗兰克·赫伯特", 8),
    fixtureWork("work-3", "人类简史", "尤瓦尔·赫拉利", null),
    fixtureWork("work-4", "银河帝国", "艾萨克·阿西莫夫", null),
    fixtureWork("work-5", "百年孤独", "加西亚·马尔克斯", null),
    fixtureWork("work-6", "活着", "余华", null),
)

private fun fixtureWork(id: String, title: String, author: String, progress: Int?): WorkCard = WorkCard(
    id = id,
    title = title,
    author = author,
    coverUrl = "fixture://cover/$id",
    mediaKinds = listOf("EBOOK"),
    progressPercent = progress,
)

private val fixtureDetail = WorkDetailContent(
    work = fixtureWorks.first(),
    seriesId = "series-three-body",
    seriesName = "三体系列",
    authorFacetId = "author-liu-cixin",
    description = "在文明与宇宙的尺度上，人类第一次直面来自群星深处的未知回声。",
    tags = listOf("科幻", "长篇小说"),
    media = listOf(
        MediaContent(
            kind = "EBOOK",
            volumes = listOf(
                fixtureVolume("volume-1", "第一卷 地球往事", 100, true),
                fixtureVolume("volume-2", "第二卷 黑暗森林", 34, true),
                fixtureVolume("volume-3", "第三卷 死神永生", null, true),
                fixtureVolume("volume-4", "第四卷 宇宙回声", null, true),
            ),
        ),
        MediaContent(kind = "COMIC", volumes = listOf(fixtureVolume("comic-1", "漫画版 第一卷", null, true))),
        MediaContent(kind = "AUDIOBOOK", volumes = listOf(fixtureVolume("audio-1", "有声版", 12, true))),
    ),
    selectedMediaKind = "EBOOK",
    readingUnits = listOf(
        ReadingUnitContent("chapter-1", "第一章 科学边界", 100, readingState = ChapterReadingState.Read),
        ReadingUnitContent("chapter-2", "第二章 黑暗森林", 34, readingState = ChapterReadingState.Current),
        ReadingUnitContent("chapter-3", "第三章 遥远回声", readingState = ChapterReadingState.Unread),
    ),
)

private val fixtureSingleEbookDetail = WorkDetailContent(
    work = fixtureWorks[1].copy(mediaKinds = listOf("EBOOK"), progressPercent = 42),
    seriesId = "series-dune",
    seriesName = "沙丘系列",
    authorFacetId = "author-frank-herbert",
    description = null,
    tags = listOf("科幻"),
    media = listOf(
        MediaContent(
            kind = "EBOOK",
            volumes = listOf(fixtureVolume("single-ebook-1", "沙丘", 42, true)),
        ),
    ),
    selectedMediaKind = "EBOOK",
    readingUnits = listOf(
        ReadingUnitContent("dune-chapter-1", "第一章 厄拉科斯", 100, readingState = ChapterReadingState.Read),
        ReadingUnitContent("dune-chapter-2", "第二章 沙漠之路", 42, readingState = ChapterReadingState.Current),
        ReadingUnitContent("dune-chapter-3", "第三章 香料", readingState = ChapterReadingState.Unread),
    ),
)

private fun WorkDetailContent.coverPaths(): List<String> =
    media.flatMap(MediaContent::volumes).map(VolumeContent::coverUrl)

private fun fixtureVolume(id: String, title: String, progress: Int?, readable: Boolean): VolumeContent = VolumeContent(
    id = id,
    title = title,
    format = "EPUB",
    readerType = "reflowable",
    volumeIndex = id.substringAfterLast('-').toDoubleOrNull(),
    publishedAt = "2010-11-01",
    language = "zh-CN",
    pageCount = 428,
    metadataSource = "内嵌元数据",
    files = listOf(
        VolumeFileContent(
            id = "file-$id",
            path = "/library/三体系列/$title.epub",
            sizeBytes = 3_200_000,
            displaySize = "3.2 MB",
        ),
    ),
    coverUrl = "fixture://cover/$id",
    sizeBytes = 3_200_000,
    progressPercent = progress,
    readable = readable,
    selected = id == "volume-2",
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
        source = com.ermao.library.shared.modules.library.ContentSource.Network,
    )

    override suspend fun loadHome(context: ContentRequestContext): ContentResult<HomeSnapshot> = forbidden("loadHome")
    override suspend fun loadContinueReading(context: ContentRequestContext) = forbidden("loadContinueReading")
    override suspend fun loadRecentReading(context: ContentRequestContext, limit: Int) = forbidden("loadRecentReading")
    override suspend fun loadRecentAdded(context: ContentRequestContext, limit: Int) = forbidden("loadRecentAdded")
    override suspend fun loadWorks(context: ContentRequestContext, query: WorksQuery): ContentResult<LibraryPage<WorkSummary>> = forbidden("loadWorks")
    override suspend fun loadGroupings(context: ContentRequestContext, query: GroupingQuery): ContentResult<LibraryPage<GroupingSummary>> = forbidden("loadGroupings")
    override suspend fun loadFacet(context: ContentRequestContext, query: FacetQuery): ContentResult<FacetPage> = forbidden("loadFacet")
    override suspend fun loadWorkDetail(context: ContentRequestContext, query: WorkDetailQuery): ContentResult<WorkDetailSummary> = forbidden("loadWorkDetail")
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
