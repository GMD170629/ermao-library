package com.ermao.library.features.home.ui

import android.content.Context
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertLeftPositionInRootIsEqualTo
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.R
import com.ermao.library.features.content.model.ContinueReadingCard
import com.ermao.library.features.content.model.HomeContent
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.home.application.HomeUiState
import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.library.AuthenticatedCover
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.ContentResult
import com.ermao.library.shared.modules.library.ContentSource
import com.ermao.library.shared.modules.library.FacetPage
import com.ermao.library.shared.modules.library.FacetQuery
import com.ermao.library.shared.modules.library.GroupingQuery
import com.ermao.library.shared.modules.library.GroupingSummary
import com.ermao.library.shared.modules.library.HomeSnapshot
import com.ermao.library.shared.modules.library.LibraryPage
import com.ermao.library.shared.modules.library.WorksQuery
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.ui.theme.WarmPageTheme
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class HomeScreenTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun dailyStateUsesCompactGutterThreeScanTargetsAndOneTruthfulPrimaryAction() {
        val renderedContext = AtomicReference<Context>()
        var openedWorkId: String? = null
        compose.setContent {
            renderedContext.set(LocalContext.current)
            WarmPageTheme {
                HomeScreen(
                    state = HomeUiState(
                        isLoading = false,
                        content = dailyHomeContent(),
                    ),
                    repository = StubContentRepository,
                    context = contentRequestContext(),
                    onOpenWork = { openedWorkId = it },
                    onOpenLibrary = {},
                    onRetry = {},
                    onRefresh = {},
                    lastReadClock = FixedHomeTestClock,
                )
            }
        }

        compose.waitForIdle()
        val context = checkNotNull(renderedContext.get())
        compose.onNodeWithTag("home-continue")
            .assertIsDisplayed()
            .assertLeftPositionInRootIsEqualTo(16.dp)
        compose.onNodeWithTag("work-recent-1").assertIsDisplayed()
        compose.onNodeWithTag("work-recent-2").assertIsDisplayed()
        compose.onNodeWithTag("work-recent-3").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.home_view_detail_action))
            .assertIsDisplayed()
            .assertHeightIsAtLeast(48.dp)
            .performClick()

        assertEquals("continue-work", openedWorkId)
    }

    @Test
    fun defaultFontContinueCardCompactsDuplicateMetadataAndNeverShowsWireTimestamp() {
        val longTitle = "A Deliberately Long Work Title That Needs Two Lines"
        val wireTimestamp = "2026-08-15T13:47:38.286000Z"
        compose.setContent {
            WarmPageTheme {
                HomeScreen(
                    state = HomeUiState(
                        isLoading = false,
                        content = HomeContent(
                            continueReading = ContinueReadingCard(
                                work = work("long-work", longTitle, progress = 72),
                                volumeTitle = "  $longTitle  ",
                                positionLabel = " $longTitle ",
                                lastReadAtEpochMillis = Instant.parse(wireTimestamp).toEpochMilli(),
                            ),
                            recentReading = emptyList(),
                            recentAdded = emptyList(),
                        ),
                    ),
                    repository = StubContentRepository,
                    context = contentRequestContext(),
                    onOpenWork = {},
                    onOpenLibrary = {},
                    onRetry = {},
                    onRefresh = {},
                    lastReadClock = FixedHomeTestClock,
                )
            }
        }

        compose.waitForIdle()
        val continueCard = compose.onNodeWithTag("home-continue").assertIsDisplayed()
        val continueCardBounds = continueCard.getUnclippedBoundsInRoot()
        assertTrue(
            "Continue card should stay within the compact default-font height budget",
            continueCardBounds.bottom - continueCardBounds.top <= 248.dp,
        )
        compose.onAllNodesWithText(longTitle).assertCountEquals(1)
        compose.onNodeWithTag("home-continue-position").assertDoesNotExist()
        compose.onNodeWithText(wireTimestamp).assertDoesNotExist()
        compose.onNodeWithTag(
            testTag = "home-continue-progress-summary",
            useUnmergedTree = true,
        )
            .performScrollTo()
            .assertIsDisplayed()
    }
}

private val FixedHomeTestClock: Clock = Clock.fixed(
    Instant.parse("2026-08-15T14:00:00Z"),
    ZoneId.of("Asia/Shanghai"),
)

private fun dailyHomeContent(): HomeContent = HomeContent(
    continueReading = ContinueReadingCard(
        work = work("continue-work", "The Three-Body Problem", progress = 34),
        volumeTitle = "Volume 1",
        positionLabel = "Chapter 2",
        lastReadAtEpochMillis = Instant.parse("2026-08-15T01:18:00Z").toEpochMilli(),
    ),
    recentReading = listOf(
        work("recent-1", "Dune", progress = 12),
        work("recent-2", "Sapiens", progress = 8),
        work("recent-3", "The Milky Way", progress = 18),
    ),
    recentAdded = emptyList(),
)

private fun work(id: String, title: String, progress: Int?): WorkCard = WorkCard(
    id = id,
    title = title,
    author = "Author",
    coverUrl = "/covers/$id",
    mediaKinds = listOf("EBOOK"),
    progressPercent = progress,
)

private fun contentRequestContext(): ContentRequestContext {
    val parsed = ServerBaseUrl.parse("https://books.example.com")
    check(parsed is ServerBaseUrlParseResult.Valid)
    val profile = ServerProfile(
        id = "home-test-profile",
        displayName = "Home Library",
        baseUrl = parsed.baseUrl,
        serverIdentity = "home-test-server",
        isActive = true,
        tlsMode = TlsMode.SystemTrust,
    )
    return ContentRequestContext(
        profile = profile,
        namespace = PrivateDataNamespace(profile.serverIdentity, "home-test-user", 1),
    )
}

private object StubContentRepository : ContentRepository {
    override suspend fun loadHome(context: ContentRequestContext): ContentResult<HomeSnapshot> = unused()

    override suspend fun loadContinueReading(
        context: ContentRequestContext,
    ): ContentResult<com.ermao.library.shared.modules.library.ContinueReadingItem?> = unused()

    override suspend fun loadRecentReading(
        context: ContentRequestContext,
        limit: Int,
    ): ContentResult<List<WorkSummary>> = unused()

    override suspend fun loadRecentAdded(
        context: ContentRequestContext,
        limit: Int,
    ): ContentResult<List<WorkSummary>> = unused()

    override suspend fun loadWorks(
        context: ContentRequestContext,
        query: WorksQuery,
    ): ContentResult<LibraryPage<WorkSummary>> = unused()

    override suspend fun loadGroupings(
        context: ContentRequestContext,
        query: GroupingQuery,
    ): ContentResult<LibraryPage<GroupingSummary>> = unused()

    override suspend fun loadFacet(
        context: ContentRequestContext,
        query: FacetQuery,
    ): ContentResult<FacetPage> = unused()

    override suspend fun loadWorkDetail(
        context: ContentRequestContext,
        query: com.ermao.library.shared.modules.library.WorkDetailQuery,
    ): ContentResult<WorkDetailSummary> = unused()

    override suspend fun loadCover(
        context: ContentRequestContext,
        apiPath: String,
        etag: String?,
    ): ContentResult<AuthenticatedCover> = ContentResult.Content(
        value = AuthenticatedCover(ByteArray(0), null, null),
        source = ContentSource.Network,
    )

    override suspend fun invalidate(namespace: PrivateDataNamespace) = Unit

    private fun unused(): Nothing = error("This repository operation is not used by the Home UI test")
}
