package com.ermao.library.features.library.ui

import androidx.compose.ui.unit.dp
import com.ermao.library.features.content.model.BookCard
import com.ermao.library.features.content.model.BookDetailContent
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.library.application.WorkDetailUiState
import com.ermao.library.features.content.ui.compactCoverGridColumnCount
import com.ermao.library.features.content.ui.compactCoverGridItemWidth
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.downloads.model.AndroidDownloadStatus
import com.ermao.library.features.downloads.model.AndroidDownloadNamespace
import com.ermao.library.shared.modules.library.BookContentEntry
import com.ermao.library.shared.modules.library.BookContentsPage
import com.ermao.library.shared.modules.library.BookDetailPresentation
import com.ermao.library.shared.modules.library.BookDetailObjectKind
import com.ermao.library.shared.modules.library.BookDetailDownloadState
import java.util.Locale
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import org.junit.Test

class WorkDetailLayoutTest {
    @Test
    fun workContentPresentationMatchesWebDirectoryAndResourceRules() {
        fun entry(
            id: String,
            title: String,
            kind: String,
            resourceId: String? = null,
            representativeResourceId: String? = null,
            coverUrl: String? = null,
        ) = BookContentEntry(
            sourceNodeId = id,
            parentSourceNodeId = "root",
            name = title,
            title = title,
            description = null,
            kind = kind,
            physicalKind = if (kind == "FOLDER") "DIRECTORY" else "REGULAR_FILE",
            sizeBytes = null,
            observedAt = "2026-08-26T00:00:00Z",
            hasChildren = kind == "FOLDER",
            resourceId = resourceId,
            representativeResourceId = representativeResourceId,
            coverUrl = coverUrl,
        )
        val resources = listOf(
            ResourceContent(
                id = "representative-1",
                title = "Representative 1",
                format = "CBR",
                coverUrl = "/representative-cover",
                progressPercent = null,
                readable = true,
                selected = false,
            ),
            ResourceContent(
                id = "representative-2",
                title = "Representative 2",
                format = "ZIP",
                coverUrl = "/ignored-cover",
                progressPercent = null,
                readable = true,
                selected = false,
            ),
            ResourceContent(
                id = "direct",
                title = "01 Launch",
                format = "CBZ",
                resourceIndex = 7.0,
                coverUrl = "/resource-cover",
                progressPercent = 25,
                readable = true,
                selected = false,
            ),
        )
        val root = entry("root", "Star Harbor", "FOLDER")
        val page = BookContentsPage(
            bookId = "book-1",
            currentSourceNodeId = root.sourceNodeId,
            currentResourceId = null,
            currentNode = root,
            currentResourceIds = listOf("direct"),
            parentSourceNodeId = null,
            breadcrumbs = emptyList(),
            entries = listOf(
                entry("direct-node", "01 Launch.cbz", "FILE", resourceId = "direct"),
                entry(
                    "directory-1",
                    "Single Volumes",
                    "FOLDER",
                    representativeResourceId = "representative-1",
                ),
                entry(
                    "directory-2",
                    "Color Edition",
                    "FOLDER",
                    representativeResourceId = "representative-2",
                    coverUrl = "/entry-cover",
                ),
                entry("directory-3", "Extras", "FOLDER"),
            ),
            page = 1,
            pageSize = 100,
            total = 4,
            totalPages = 1,
        )

        val items = workContentItemPresentations(page, resources, bookCoverUrl = "/book-cover")

        assertEquals(
            listOf(
                WorkContentItemKind.SourceDirectory,
                WorkContentItemKind.SourceDirectory,
                WorkContentItemKind.SourceDirectory,
                WorkContentItemKind.ReadableResource,
            ),
            items.map { it.kind },
        )
        assertEquals(
            listOf("Single Volumes", "Color Edition", "Extras", "01 Launch"),
            items.map { it.title },
        )
        assertEquals(
            listOf("/representative-cover", "/entry-cover", "/book-cover", "/resource-cover"),
            items.map { it.coverUrl },
        )
        assertEquals(listOf("01", "02", "03", "07"), items.map { it.indexLabel })

        val bookContent = BookDetailContent(
            book = BookCard("book-1", "Book title", "Book author", "/book-cover", 50),
            seriesId = null, seriesName = null, authorFacetId = null,
            description = "Book introduction", tags = listOf("Book tag"),
            resources = resources, selectedResourceId = null, continueResourceId = "direct",
        )
        val rootState = WorkDetailUiState(isLoading = false, content = bookContent, contents = page)
        assertEquals(BookDetailObjectKind.Book, rootState.detailActionScope()?.objectKind)
        assertEquals("book-1", rootState.detailActionScope()?.objectId)
        assertEquals("direct", rootState.resolveReadingResource()?.id)
        val anotherResume = rootState.copy(content = bookContent.copy(continueResourceId = "representative-1"))
        assertEquals("book-1", anotherResume.detailActionScope()?.objectId)
        assertEquals("representative-1", anotherResume.resolveReadingResource()?.id)
        val childResourceState = rootState.copy(isBookRoot = false, selectedResourceId = "direct")
        assertEquals(BookDetailObjectKind.Resource, childResourceState.detailActionScope()?.objectKind)
        assertEquals("direct", childResourceState.detailActionScope()?.objectId)
        assertNull(rootState.copy(isBookRoot = false).detailActionScope())
        val rootPresentation = assertNotNull(workDetailPageContent(rootState))
        assertEquals("direct", rootPresentation.continueResource?.id)
        assertEquals(25, rootPresentation.continueResource?.progressPercent)
        assertEquals(WorkDetailPrimaryActionLabel.ContinueReading, workDetailPrimaryActionPresentation(rootPresentation.continueResource, null).label)
        assertNull(bookContent.copy(continueResourceId = "missing").continueResource)
        assertNull(bookContent.copy(continueResourceId = null).continueResource)
        val unread = resources.last().copy(progressPercent = null)
        assertEquals(WorkDetailPrimaryActionLabel.StartReading, workDetailPrimaryActionPresentation(unread, null).label)
        assertEquals(WorkDetailPrimaryActionLabel.StartListening, workDetailPrimaryActionPresentation(unread.copy(readerType = "audio"), null).label)
        assertEquals("Book title", rootPresentation.book.title)
        assertEquals("Book introduction", rootPresentation.description)
        assertEquals("/book-cover", rootPresentation.book.coverUrl)
        assertEquals(listOf("Book tag"), rootPresentation.tags)
        assertNull(rootPresentation.book.progressPercent)

        val childPresentation = assertNotNull(workDetailPageContent(rootState.copy(isBookRoot = false)))
        assertEquals("Star Harbor", childPresentation.book.title)
        assertNull(childPresentation.description)
        val resourcePresentation = assertNotNull(workDetailPageContent(rootState.copy(
            presentation = BookDetailPresentation.ResourceDetail, selectedResourceId = "direct",
        )))
        assertEquals("01 Launch", resourcePresentation.book.title)
        assertEquals("/resource-cover", resourcePresentation.book.coverUrl)
        assertEquals(25, resourcePresentation.book.progressPercent)
    }

    @Test
    fun workContentBreadcrumbsUseBookTitleOnceAndOnlyApiBreadcrumbsAfterIt() {
        fun entry(id: String, title: String) = BookContentEntry(
            sourceNodeId = id,
            parentSourceNodeId = if (id == "root") null else "root",
            name = title,
            title = title,
            description = null,
            kind = "FOLDER",
            physicalKind = "DIRECTORY",
            sizeBytes = null,
            observedAt = "2026-08-26T00:00:00Z",
            hasChildren = true,
            resourceId = null,
            representativeResourceId = null,
            coverUrl = null,
        )
        val root = entry("root", "Star Harbor")
        val directory = entry("single-volumes", "Single Volumes")
        val rootPage = BookContentsPage(
            bookId = "book-1",
            currentSourceNodeId = root.sourceNodeId,
            currentResourceId = null,
            currentNode = root,
            currentResourceIds = emptyList(),
            parentSourceNodeId = null,
            breadcrumbs = emptyList(),
            entries = emptyList(),
            page = 1,
            pageSize = 100,
            total = 0,
            totalPages = 1,
        )
        val nestedPage = rootPage.copy(
            currentSourceNodeId = directory.sourceNodeId,
            currentNode = directory,
            parentSourceNodeId = root.sourceNodeId,
            breadcrumbs = listOf(directory),
        )

        assertEquals(listOf("Star Harbor"), workContentBreadcrumbs("Star Harbor", rootPage).map { it.title })
        assertEquals(
            listOf("Star Harbor", "Single Volumes"),
            workContentBreadcrumbs("Star Harbor", nestedPage).map { it.title },
        )
    }

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
    fun audiobookActionOpensOnlinePlayerWithoutACompletedDownload() {
        val audiobook = testResource(readerType = "audio", format = "M4B", progressPercent = 12)

        assertEquals(
            WorkDetailPrimaryActionIntent.OpenSelectedVolume,
            workDetailPrimaryActionPresentation(audiobook, download = null).intent,
        )
        assertTrue(
            workDetailPrimaryActionPresentation(audiobook, download = null).enabled,
        )
    }

    @Test
    fun reflowableProgressKeepsDownloadIndependentFromOnlineReading() {
        val currentResource = testResource(
            readerType = "reflowable",
            format = "EPUB",
            progressPercent = 34,
        )

        val resource = workDetailVolumePresentation(
            resource = currentResource,
            selected = true,
            download = null,
        )
        val primaryAction = workDetailPrimaryActionPresentation(
            selectedResource = currentResource,
            download = null,
        )

        assertTrue(resource.selected)
        assertEquals(WorkDetailVolumeReadingState.Reading, resource.readingState)
        assertEquals(WorkDetailVolumeDownloadState.NotDownloaded, resource.downloadState)
        assertEquals(3.dp, WORK_DETAIL_SELECTED_VOLUME_BORDER_WIDTH)
        assertEquals(WorkDetailPrimaryActionIntent.OpenSelectedVolume, primaryAction.intent)
        assertEquals(WorkDetailPrimaryActionLabel.ContinueReading, primaryAction.label)
        assertTrue(primaryAction.enabled)
    }

    @Test
    fun completedArtifactDoesNotChangeTheOnlineReaderIntent() {
        val resource = testResource(readerType = "reflowable", format = "EPUB", progressPercent = 34)
        val completedDownload = completedDownload(resource)

        assertEquals(
            WorkDetailPrimaryActionIntent.OpenSelectedVolume,
            workDetailPrimaryActionPresentation(resource, completedDownload).intent,
        )
        assertEquals(
            WorkDetailPrimaryActionLabel.ContinueReading,
            workDetailPrimaryActionPresentation(resource, completedDownload).label,
        )

        assertEquals(
            WorkDetailPrimaryActionIntent.OpenSelectedVolume,
            workDetailPrimaryActionPresentation(
                resource.copy(id = "different-resource"),
                completedDownload,
            ).intent,
        )
    }

    @Test
    fun supportedOnlineFormatsOpenReaderWithoutCompletedArtifacts() {
        val formats = listOf(
            "reflowable" to "EPUB",
            "reflowable" to "MOBI",
            "reflowable" to "AZW",
            "reflowable" to "AZW3",
            "reflowable" to "PRC",
            "reflowable" to "FB2",
            "reflowable" to "TXT",
            "comic" to "CBZ",
            "pdf" to "PDF",
        )

        formats.forEach { (readerType, format) ->
            val resource = testResource(readerType = readerType, format = format, progressPercent = null)
            assertEquals(
                WorkDetailPrimaryActionIntent.OpenSelectedVolume,
                workDetailPrimaryActionPresentation(resource, download = null).intent,
                format,
            )
            assertEquals(
                WorkDetailVolumeDownloadState.NotDownloaded,
                workDetailVolumePresentation(resource, selected = true, download = null).downloadState,
                format,
            )
        }
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
        val resource = testResource(readerType = "reflowable", format = "EPUB", progressPercent = 34)
        val completed = completedDownload(resource)
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
        assertEquals(BookDetailSummaryLayout.Inline, workDetailSummaryLayout(fontScale = 1.49f))
        assertEquals(BookDetailSummaryLayout.Stacked, workDetailSummaryLayout(fontScale = 1.5f))
        assertEquals(BookDetailSummaryLayout.Stacked, workDetailSummaryLayout(fontScale = 2f))
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
    fun volumeRailAndPageGridUseTheSameCoverWidthAsHomeShelves() {
        val standardColumns = compactCoverGridColumnCount(
            compactColumns = 3,
            largeTextColumns = 2,
            fontScale = 1f,
        )
        val accessibilityColumns = compactCoverGridColumnCount(
            compactColumns = 3,
            largeTextColumns = 2,
            fontScale = 1.5f,
        )
        val standard = compactCoverGridItemWidth(
            availableWidth = 360.dp,
            horizontalGap = 12.dp,
            columns = standardColumns,
        )
        val accessibility = compactCoverGridItemWidth(
            availableWidth = 360.dp,
            horizontalGap = 12.dp,
            columns = accessibilityColumns,
        )

        assertEquals(112.dp, standard)
        assertEquals(174.dp, accessibility)
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

    @Test
    fun bookDownloadSummaryIncludesOtherVolumesButNeverOtherBooks() {
        val resource = testResource("reflowable", "EPUB", 30)
        val completed = completedDownload(resource)
        val otherVolume = completed.copy(resourceId = "other-volume", status = AndroidDownloadStatus.Downloading, verified = false, localReference = null)
        val unrelated = completed.copy(bookId = "other-book", resourceId = "outside")
        val summary = workBookDownloadSummary("book-1", listOf(completed, otherVolume, unrelated))
        assertEquals(BookDetailDownloadState.Downloading, summary.state)
        assertEquals(1, summary.downloadedResources)
        assertEquals(2, workBookDownloadSummary("book-1", listOf(completed, completed.copy(resourceId = "other-volume"), unrelated)).downloadedResources)
        assertEquals(BookDetailDownloadState.NotDownloaded, workBookDownloadSummary("missing", listOf(completed)).state)
    }

    private fun testResource(
        readerType: String,
        format: String,
        progressPercent: Int?,
        readable: Boolean = true,
    ): ResourceContent = ResourceContent(
        id = "resource-2",
        title = "Resource Two",
        format = format,
        readerType = readerType,
        progressPercent = progressPercent,
        readable = readable,
        selected = true,
    )

    private fun completedDownload(resource: ResourceContent): AndroidDownloadRecord = AndroidDownloadRecord(
        taskId = "task-2",
        namespace = AndroidDownloadNamespace("server", "user", 1),
        bookId = "book-1",
        bookTitle = "Book",
        author = "Author",
        coverUrl = "",
        resourceId = resource.id,
        resourceTitle = resource.title,
        format = resource.format,
        readerType = resource.readerType,
        assetId = resource.assets.firstOrNull()?.id ?: "asset-${resource.id}",
        sourceApiPath = "/api/resources/${resource.id}/asset",
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
