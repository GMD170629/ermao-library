package com.ermao.library.features.library.ui

import androidx.compose.ui.unit.dp
import com.ermao.library.features.content.model.VolumeContent
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import java.util.Locale
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.Test

class WorkDetailLayoutTest {
    @Test
    fun selectedVolumePublicationDateUsesTheActiveLocaleAndPreservesUnknownValues() {
        assertEquals("Nov 1, 2010", formatWorkMetadataDate("2010-11-01T00:00:00Z", Locale.US))
        assertEquals("legacy date", formatWorkMetadataDate("legacy date", Locale.US))
        assertEquals(null, formatWorkMetadataDate(" ", Locale.US))
    }

    @Test
    fun identityKeepsAuthorAndSeriesInOneMetadataLine() {
        val presentation = workDetailIdentityPresentation(
            tags = listOf("科幻", "", "Long-form", "long-form"),
            completed = false,
            progressPercent = 34,
        )

        assertEquals(listOf("科幻", "Long-form"), presentation.tags)
        assertEquals(null, presentation.status)
        assertEquals(
            listOf(
                WorkDetailIdentityElement.Title,
                WorkDetailIdentityElement.AuthorAndSeries,
                WorkDetailIdentityElement.Tags,
            ),
            presentation.elements,
        )
    }

    @Test
    fun defaultIdentityOmitsStatusWhileCompletedIdentityOverridesProgress() {
        assertEquals(
            listOf(WorkDetailIdentityElement.Title, WorkDetailIdentityElement.AuthorAndSeries),
            workDetailIdentityPresentation(
                tags = emptyList(),
                completed = false,
                progressPercent = 0,
            ).elements,
        )
        assertEquals(
            null,
            workDetailIdentityPresentation(
                tags = emptyList(),
                completed = true,
                progressPercent = 62,
            ).status,
        )
    }

    @Test
    fun descriptionActionOnlyAppearsForOverflowAndRemainsAvailableToCollapse() {
        assertEquals(false, workDetailDescriptionActionVisible(expanded = false, collapsedHasOverflow = false))
        assertEquals(true, workDetailDescriptionActionVisible(expanded = false, collapsedHasOverflow = true))
        assertEquals(true, workDetailDescriptionActionVisible(expanded = true, collapsedHasOverflow = true))
    }

    @Test
    fun audiobookActionStaysUnavailableUntilTheNowPlayingDestinationExists() {
        val audiobook = testVolume(readerType = "audio", format = "M4B", progressPercent = 12)

        assertEquals(
            WorkDetailPrimaryActionIntent.Unavailable,
            workDetailPrimaryActionPresentation("AUDIOBOOK", audiobook, download = null).intent,
        )
        assertFalse(
            workDetailPrimaryActionPresentation("AUDIOBOOK", audiobook, download = null).enabled,
        )
    }

    @Test
    fun reflowableProgressDoesNotPretendThePublicationArtifactIsDownloaded() {
        val currentVolume = testVolume(
            readerType = "reflowable",
            format = "EPUB",
            progressPercent = 34,
        )

        val volume = workDetailVolumePresentation(
            volume = currentVolume,
            selected = true,
            download = null,
        )
        val primaryAction = workDetailPrimaryActionPresentation(
            mediaKind = "EBOOK",
            selectedVolume = currentVolume,
            download = null,
        )

        assertTrue(volume.selected)
        assertEquals(WorkDetailVolumeReadingState.Reading, volume.readingState)
        assertEquals(WorkDetailVolumeDownloadState.NotDownloaded, volume.downloadState)
        assertEquals(3.dp, WORK_DETAIL_SELECTED_VOLUME_BORDER_WIDTH)
        assertEquals(WorkDetailPrimaryActionIntent.DownloadThenRead, primaryAction.intent)
        assertEquals(WorkDetailPrimaryActionLabel.DownloadToRead, primaryAction.label)
        assertTrue(primaryAction.enabled)
    }

    @Test
    fun onlyACompletedReflowableArtifactChangesThePrimaryIntentToReader() {
        val volume = testVolume(readerType = "reflowable", format = "EPUB", progressPercent = 34)
        val completedDownload = completedDownload(volume)

        assertEquals(
            WorkDetailPrimaryActionIntent.OpenSelectedVolume,
            workDetailPrimaryActionPresentation("EBOOK", volume, completedDownload).intent,
        )
        assertEquals(
            WorkDetailPrimaryActionLabel.ContinueReading,
            workDetailPrimaryActionPresentation("EBOOK", volume, completedDownload).label,
        )

        assertEquals(
            WorkDetailPrimaryActionIntent.DownloadThenRead,
            workDetailPrimaryActionPresentation(
                "EBOOK",
                volume.copy(id = "different-volume"),
                completedDownload,
            ).intent,
        )
    }

    @Test
    fun comicAndPdfRemainRemoteStreamEntriesWithoutCompletedArtifacts() {
        assertEquals(
            WorkDetailPrimaryActionIntent.OpenSelectedVolume,
            workDetailPrimaryActionPresentation(
                mediaKind = "COMIC",
                selectedVolume = testVolume(readerType = "comic", format = "CBZ", progressPercent = null),
                download = null,
            ).intent,
        )
        assertEquals(
            WorkDetailPrimaryActionIntent.OpenSelectedVolume,
            workDetailPrimaryActionPresentation(
                mediaKind = "EBOOK",
                selectedVolume = testVolume(readerType = "pdf", format = "PDF", progressPercent = null),
                download = null,
            ).intent,
        )
    }

    @Test
    fun readingStatusDerivesAllThreeStableSingleChoiceStates() {
        assertEquals(WorkReadingStatus.Unread, workReadingStatus(completed = false, progressPercent = 0))
        assertEquals(WorkReadingStatus.Reading, workReadingStatus(completed = false, progressPercent = 34))
        assertEquals(WorkReadingStatus.Finished, workReadingStatus(completed = true, progressPercent = 34))
        assertEquals(WorkReadingStatus.Finished, nextWorkReadingStatus(WorkReadingStatus.Unread))
        assertEquals(WorkReadingStatus.Finished, nextWorkReadingStatus(WorkReadingStatus.Reading))
        assertEquals(WorkReadingStatus.Unread, nextWorkReadingStatus(WorkReadingStatus.Finished))
        assertEquals(
            listOf(WorkReadingStatus.Unread, WorkReadingStatus.Finished),
            workReadingStatusChoices(),
        )
    }

    @Test
    fun controlDownloadStateReflectsTheSelectedVolumeAndKeepsCompletedRemovalExplicit() {
        val volume = testVolume(readerType = "reflowable", format = "EPUB", progressPercent = 34)
        val completed = completedDownload(volume)
        val paused = completed.copy(
            status = AndroidDownloadStatus.Paused,
            verified = false,
            localReference = null,
        )
        val failed = paused.copy(status = AndroidDownloadStatus.FailedRetryable)

        assertEquals(WorkDetailDownloadAction.NotDownloaded, workDetailDownloadActionPresentation(null))
        assertEquals(WorkDetailDownloadAction.Paused, workDetailDownloadActionPresentation(paused))
        assertEquals(WorkDetailDownloadAction.Failed, workDetailDownloadActionPresentation(failed))
        assertEquals(WorkDetailDownloadAction.Downloaded, workDetailDownloadActionPresentation(completed))
    }

    @Test
    fun readingSummaryStacksBeforeLargeTextCanTruncateItsPosition() {
        assertEquals(WorkDetailSummaryLayout.Inline, workDetailSummaryLayout(fontScale = 1.49f))
        assertEquals(WorkDetailSummaryLayout.Stacked, workDetailSummaryLayout(fontScale = 1.5f))
        assertEquals(WorkDetailSummaryLayout.Stacked, workDetailSummaryLayout(fontScale = 2f))
    }

    @Test
    fun mediaPickerBecomesFullWidthChoicesAtLargeText() {
        assertEquals(
            WorkDetailMediaPickerLayout.Segmented,
            workDetailMediaPickerLayout(availableWidth = 360.dp, fontScale = 1.49f),
        )
        assertEquals(
            WorkDetailMediaPickerLayout.VerticalChoices,
            workDetailMediaPickerLayout(availableWidth = 360.dp, fontScale = 1.5f),
        )
        assertEquals(
            WorkDetailMediaPickerLayout.VerticalChoices,
            workDetailMediaPickerLayout(availableWidth = 360.dp, fontScale = 2f),
        )
    }

    @Test
    fun mediaPickerKeepsEachAvailableOptionAtTheDesignSegmentWidth() {
        assertEquals(80.dp, workDetailMediaControlWidth(optionCount = 1))
        assertEquals(160.dp, workDetailMediaControlWidth(optionCount = 2))
        assertEquals(240.dp, workDetailMediaControlWidth(optionCount = 3))
    }

    @Test
    fun volumeRailShowsAboutThreeCoversAndExpandsForLargeText() {
        val standard = workDetailVolumeRailItemWidth(
            availableWidth = 360.dp,
            gap = 12.dp,
            fontScale = 1f,
        )
        val accessibility = workDetailVolumeRailItemWidth(
            availableWidth = 360.dp,
            gap = 12.dp,
            fontScale = 1.5f,
        )

        assertEquals(105.dp, standard)
        assertTrue(accessibility > standard)
    }

    @Test
    fun narrowEnglishLayoutStacksActionsAndUsesFullWidthMediaChoicesAtDefaultFontScale() {
        val narrowContentWidth = 312.dp

        assertEquals(
            WorkDetailActionLayout.Stacked,
            workDetailActionLayout(
                availableWidth = narrowContentWidth,
                fontScale = 1f,
                requiredInlineWidth = 360.dp,
            ),
        )
        assertEquals(
            WorkDetailMediaPickerLayout.VerticalChoices,
            workDetailMediaPickerLayout(availableWidth = narrowContentWidth, fontScale = 1f),
        )
    }

    @Test
    fun regularCompactWidthKeepsActionsAndMediaControlInlineAtDefaultFontScale() {
        val compactContentWidth = 360.dp

        assertEquals(
            WorkDetailActionLayout.Inline,
            workDetailActionLayout(
                availableWidth = compactContentWidth,
                fontScale = 1f,
                requiredInlineWidth = 359.dp,
            ),
        )
        assertEquals(
            WorkDetailMediaPickerLayout.Segmented,
            workDetailMediaPickerLayout(availableWidth = compactContentWidth, fontScale = 1f),
        )
    }

    @Test
    fun englishReadingActionsStackUntilBothLabelsAndIconsFitAtTheProductionBoundary() {
        val requiredInlineWidth = minimumWorkDetailInlineActionWidth(
            secondaryLabelWidth = 91.dp,
            primaryLabelWidth = 125.5.dp,
            iconSize = 24.dp,
            iconLabelGap = 8.dp,
            horizontalContentPadding = 8.dp,
            actionGap = 12.dp,
        )

        assertEquals(359.dp, requiredInlineWidth)
        assertEquals(
            WorkDetailActionLayout.Stacked,
            workDetailActionLayout(
                availableWidth = 328.dp,
                fontScale = 1f,
                requiredInlineWidth = requiredInlineWidth,
            ),
        )
        assertEquals(
            WorkDetailActionLayout.Inline,
            workDetailActionLayout(
                availableWidth = 360.dp,
                fontScale = 1f,
                requiredInlineWidth = requiredInlineWidth,
            ),
        )
    }

    @Test
    fun contentThatRequires392DpStacksUntilItsFullLabelAndIconFit() {
        val requiredInlineWidth = minimumWorkDetailInlineActionWidth(
            secondaryLabelWidth = 91.dp,
            primaryLabelWidth = 142.dp,
            iconSize = 24.dp,
            iconLabelGap = 8.dp,
            horizontalContentPadding = 8.dp,
            actionGap = 12.dp,
        )

        assertEquals(392.dp, requiredInlineWidth)
        assertEquals(
            WorkDetailActionLayout.Stacked,
            workDetailActionLayout(
                availableWidth = 379.dp,
                fontScale = 1f,
                requiredInlineWidth = requiredInlineWidth,
            ),
        )
        assertEquals(
            WorkDetailActionLayout.Inline,
            workDetailActionLayout(
                availableWidth = requiredInlineWidth,
                fontScale = 1f,
                requiredInlineWidth = requiredInlineWidth,
            ),
        )
    }

    @Test
    fun largeTextAlwaysStacksActionsEvenWhenTheirContentWouldFitInline() {
        assertEquals(
            WorkDetailActionLayout.Stacked,
            workDetailActionLayout(
                availableWidth = 600.dp,
                fontScale = 2f,
                requiredInlineWidth = 300.dp,
            ),
        )
    }

    @Test
    fun compactPhoneUsesThreeVolumeColumns() {
        assertEquals(
            3,
            workDetailVolumeColumnCount(
                availableWidth = 328.dp,
                horizontalPadding = 16.dp,
                gap = 12.dp,
                fontScale = 1f,
            ),
        )
    }

    @Test
    fun compactVolumeGridFitsThreeReadableItemsAcrossTheAvailableWidth() {
        assertEquals(
            90.666664.dp,
            workDetailVolumeItemWidth(
                availableWidth = 328.dp,
                horizontalPadding = 16.dp,
                gap = 12.dp,
                columns = 3,
            ),
        )
    }

    @Test
    fun largeTextUsesTwoWiderVolumeItems() {
        assertEquals(
            2,
            workDetailVolumeColumnCount(
                availableWidth = 328.dp,
                horizontalPadding = 16.dp,
                gap = 12.dp,
                fontScale = 1.3f,
            ),
        )
        assertEquals(
            142.dp,
            workDetailVolumeItemWidth(
                availableWidth = 328.dp,
                horizontalPadding = 16.dp,
                gap = 12.dp,
                columns = 2,
            ),
        )
    }

    @Test
    fun expandedWidthAddsColumnsInsteadOfStretchingThreeItems() {
        assertEquals(
            5,
            workDetailVolumeColumnCount(
                availableWidth = 600.dp,
                horizontalPadding = 16.dp,
                gap = 12.dp,
                fontScale = 1f,
            ),
        )
    }

    private fun testVolume(
        readerType: String,
        format: String,
        progressPercent: Int?,
        readable: Boolean = true,
    ): VolumeContent = VolumeContent(
        id = "volume-2",
        title = "Volume Two",
        format = format,
        readerType = readerType,
        progressPercent = progressPercent,
        readable = readable,
        selected = true,
    )

    private fun completedDownload(volume: VolumeContent): AndroidDownloadRecord = AndroidDownloadRecord(
        taskId = "task-2",
        namespace = AndroidDownloadNamespace("server", "user", 1),
        workId = "work-1",
        workTitle = "Work",
        author = "Author",
        coverUrl = "",
        volumeId = volume.id,
        volumeTitle = volume.title,
        format = volume.format,
        readerType = volume.readerType,
        sourceApiPath = "/api/volumes/${volume.id}/file",
        sourceMimeType = "application/octet-stream",
        expectedBytes = 10,
        transferredBytes = 10,
        status = AndroidDownloadStatus.Completed,
        localReference = "publication.epub",
        verified = true,
        createdAtEpochMillis = 1,
        updatedAtEpochMillis = 2,
    )
}
