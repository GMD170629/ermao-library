package com.ermao.library.features.library.ui

import android.content.res.Configuration
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.features.content.model.WorksFilters
import com.ermao.library.shared.modules.library.OfflineFilterAvailability
import com.ermao.library.ui.theme.WarmPageTheme
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LibraryFilterSheetTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun englishOverrideIsCapturedBeforeModalComposition() {
        compose.setContent {
            val baseContext = LocalContext.current
            val baseConfiguration = LocalConfiguration.current
            val deviceDensity = LocalDensity.current
            val configuration = remember(baseConfiguration) {
                Configuration(baseConfiguration).apply {
                    setLocale(Locale.forLanguageTag("en-US"))
                    fontScale = 1f
                }
            }
            val localizedContext = remember(baseContext, configuration) {
                baseContext.createConfigurationContext(configuration)
            }
            CompositionLocalProvider(
                LocalContext provides localizedContext,
                LocalConfiguration provides configuration,
                LocalDensity provides Density(deviceDensity.density, configuration.fontScale),
            ) {
                val copy = resolveLibraryFilterSheetCopy()
                WarmPageTheme(darkTheme = false) {
                    FilterSheet(
                        filters = WorksFilters(),
                        copy = copy,
                        onChange = {},
                        offlineAvailability = OfflineFilterAvailability.Available,
                        onClear = {},
                        onApply = {},
                        onDismiss = {},
                    )
                }
            }
        }

        compose.onNodeWithText("Filter works").assertIsDisplayed()
        compose.onNodeWithText("Clear all").assertIsDisplayed()
        compose.onNodeWithText("Changes take effect after you apply them.").assertIsDisplayed()
        compose.onNodeWithText("Apply").assertIsDisplayed()
        compose.onNodeWithText("筛选作品").assertDoesNotExist()
    }

    @Test
    fun compactNormalTextPinsApplyWhileAllFilterOptionsRemainReachable() {
        compose.setContent {
            val deviceDensity = LocalDensity.current
            CompositionLocalProvider(
                LocalDensity provides Density(
                    density = deviceDensity.density,
                    fontScale = 1f,
                ),
            ) {
                WarmPageTheme(darkTheme = false) {
                    Box(
                        modifier = Modifier
                            .width(411.dp)
                            .height(560.dp),
                    ) {
                        LibraryFilterSheetContent(
                            filters = WorksFilters(),
                            copy = englishFilterSheetCopy(),
                            onChange = {},
                            offlineAvailability = OfflineFilterAvailability.Available,
                            onClear = {},
                            onApply = {},
                            onDismiss = {},
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }
            }
        }

        compose.onNodeWithTag("library-filter-title").assertIsDisplayed()
        val initialApplyTop = compose.onNodeWithTag("library-filter-apply")
            .assertIsDisplayed()
            .getUnclippedBoundsInRoot()
            .top

        compose.onNodeWithTag("library-filter-downloaded")
            .performScrollTo()
            .assertIsDisplayed()

        compose.onNodeWithTag("library-filter-title").assertIsDisplayed()
        val scrolledApplyTop = compose.onNodeWithTag("library-filter-apply")
            .assertIsDisplayed()
            .getUnclippedBoundsInRoot()
            .top
        assertEquals(
            "Applying filters must remain pinned while options scroll",
            initialApplyTop,
            scrolledApplyTop,
        )
        compose.onAllNodes(hasClickAction(), useUnmergedTree = true)
            .assertCountEquals(10)
    }

    @Test
    fun narrowLargeTextKeepsOneClickTargetPerControlAndCanReachTheFinalActions() {
        compose.setContent {
            val deviceDensity = LocalDensity.current
            CompositionLocalProvider(
                LocalDensity provides Density(
                    density = deviceDensity.density,
                    fontScale = 2f,
                ),
            ) {
                WarmPageTheme(darkTheme = false) {
                    Box(
                        modifier = Modifier
                            .width(320.dp)
                            .height(360.dp),
                    ) {
                        LibraryFilterSheetContent(
                            filters = WorksFilters(),
                            copy = englishFilterSheetCopy(),
                            onChange = {},
                            offlineAvailability = OfflineFilterAvailability.Available,
                            onClear = {},
                            onApply = {},
                            onDismiss = {},
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }
            }
        }

        compose.onNodeWithTag("library-filter-downloaded")
            .performScrollTo()
            .assertIsDisplayed()
        compose.onNodeWithTag("library-filter-apply")
            .assertIsDisplayed()
        compose.onAllNodes(hasClickAction(), useUnmergedTree = true)
            .assertCountEquals(10)
    }
}

private fun englishFilterSheetCopy(): LibraryFilterSheetCopy = LibraryFilterSheetCopy(
    title = "Filter works",
    description = "Changes take effect after you apply them.",
    cancelAction = "Cancel",
    clearAction = "Clear all",
    readingHeading = "Reading status",
    unread = "Unread",
    reading = "Reading",
    finished = "Finished",
    offlineHeading = "Downloaded",
    downloaded = "Downloaded",
    applyAction = "Apply",
)
