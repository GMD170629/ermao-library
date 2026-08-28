package com.ermao.library.features.shell

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.navigation3.rememberViewModelStoreNavEntryDecorator
import androidx.navigation3.runtime.NavKey
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.runtime.rememberSaveableStateHolderNavEntryDecorator
import androidx.navigation3.ui.NavDisplay
import com.ermao.library.features.content.model.LibraryScope
import com.ermao.library.features.content.model.ResourceContent
import com.ermao.library.features.downloads.application.DownloadActionsViewModel
import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import com.ermao.library.features.library.application.WorkDetailViewModel
import com.ermao.library.features.library.ui.WorkDetailScreen
import com.ermao.library.features.workmanagement.application.WorkManagementViewModel
import com.ermao.library.shared.modules.library.BookContentTarget
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.library.domain.ReadingUnit
import com.ermao.library.shared.modules.shelf.application.ShelfRepository
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
import com.ermao.library.shared.navigation.TabId
import kotlinx.serialization.Serializable

@Serializable
internal data class BookContentRoute(
    val bookId: String,
    val serverIdentity: String,
    val userId: String,
    val authorizationVersion: Long,
    val sourceTab: String,
    val target: BookContentTarget,
) : NavKey

/** One native detail stack per Book, used in both the compact destination and detail pane. */
@Composable
internal fun BookContentNavigation(
    bookId: String,
    sourceTab: TabId,
    repository: ContentRepository,
    shelfRepository: ShelfRepository,
    context: ContentRequestContext,
    managementRepository: WorkManagementRepository,
    downloads: DownloadActionsViewModel,
    canManageSystem: Boolean,
    onBack: () -> Unit,
    onUnauthorized: () -> Unit,
    onViewShelves: () -> Unit,
    onOpenFacet: (LibraryScope, String) -> Unit,
    onOpenResource: (ResourceContent) -> Unit,
    onOpenReadingUnit: (ResourceContent, ReadingUnit) -> Unit,
    onOpenDownload: (AndroidDownloadRecord) -> Unit,
) = key(context.namespace, bookId, sourceTab) {
    // The decorator retains stores in the parent Activity. A composition key alone
    // cannot distinguish identical Root targets belonging to different books/tabs.
    val root = BookContentRoute(
        bookId = bookId,
        serverIdentity = context.namespace.serverIdentity,
        userId = context.namespace.userId,
        authorizationVersion = context.namespace.authorizationVersion,
        sourceTab = sourceTab.stableValue,
        target = BookContentTarget.Root,
    )
    val backStack = rememberNavBackStack(root)
    val records by downloads.recordsByResource.collectAsStateWithLifecycle()
    val failures by downloads.failureByResource.collectAsStateWithLifecycle()
    val appContext = LocalContext.current.applicationContext
    val back = { if (backStack.size > 1) { backStack.removeLastOrNull(); Unit } else onBack() }
    val revision = com.ermao.library.features.workmanagement.managementRevision()
    val change = com.ermao.library.features.workmanagement.managementChange()
    androidx.compose.runtime.LaunchedEffect(revision) {
        if (revision > 0 && change?.bookId == bookId && change.deleted && change.resourceId != null) {
            val index = backStack.indexOfFirst { it is BookContentRoute && (it.target as? BookContentTarget.ResourceDetail)?.resourceId == change.resourceId }
            if (index > 0) while (backStack.size > index) backStack.removeLastOrNull()
        }
    }
    NavDisplay(
        backStack = backStack,
        onBack = back,
        entryDecorators = listOf(
            rememberSaveableStateHolderNavEntryDecorator(),
            rememberViewModelStoreNavEntryDecorator(),
        ),
        entryProvider = entryProvider {
            entry<BookContentRoute> { route ->
                val detail: WorkDetailViewModel = viewModel(factory = WorkDetailViewModel.factory(
                    repository, shelfRepository, context, appContext, route.bookId, onUnauthorized, route.target,
                ))
                androidx.compose.runtime.LaunchedEffect(revision) {
                    if (revision > 0 && change?.bookId == bookId) {
                        if (change.readingStatusChanged) detail.refreshAfterBookReadingStatusChange() else detail.refresh()
                    }
                }
                val state by detail.uiState.collectAsStateWithLifecycle()
                val management: WorkManagementViewModel = viewModel(factory = WorkManagementViewModel.factory(
                    managementRepository, context, route.bookId, onUnauthorized,
                ))
                val openTarget: (BookContentTarget) -> Unit = { target ->
                    val destination = root.copy(target = target)
                    val existing = backStack.indexOf(destination)
                    if (existing >= 0) {
                        while (backStack.lastIndex > existing) backStack.removeLastOrNull()
                    } else backStack.add(destination)
                }
                val openDirectory: (String?) -> Unit = { nodeId ->
                    if (nodeId == null || (nodeId == state.rootSourceNodeId && state.selectedResourceId == null)) {
                        openTarget(BookContentTarget.Root)
                    } else if (nodeId != state.contents?.currentSourceNodeId || state.selectedResourceId != null) {
                        openTarget(BookContentTarget.Directory(nodeId))
                    }
                }
                WorkDetailScreen(
                    state = state, repository = repository, context = context, onBack = back,
                    onSelectResource = { openTarget(BookContentTarget.ResourceDetail(it)) },
                    onOpenSourceNode = openDirectory,
                    onSelectContentsSort = detail::selectContentsSort,
                    onSelectContentsPage = detail::selectContentsPage,
                    onSelectReadingUnitsPage = detail::selectReadingUnitsPage,
                    onRetrySurface = detail::retrySurface,
                    onOpenShelfPicker = detail::openShelfPicker,
                    onDismissShelfPicker = detail::dismissShelfPicker,
                    onToggleShelf = detail::toggleShelf,
                    onSaveShelves = detail::saveShelves,
                    onShelfSaveFeedbackShown = detail::consumeShelfSaveCompleted,
                    onViewShelves = onViewShelves, onOpenFacet = onOpenFacet,
                    onRetry = detail::retry, onRefresh = detail::refresh,
                    onReadingStatusChanged = { scope ->
                        if (scope.includesBookActions) detail.refreshAfterBookReadingStatusChange()
                        else detail.refreshAfterReadingStatusChange(scope.objectId)
                    },
                    downloadRecordsByResource = records, downloadFailuresByResource = failures,
                    onDownloadResource = downloads::requestDownload,
                    onCancelDownload = downloads::cancelDownload, onRemoveDownload = downloads::removeDownload,
                    onOpenMultiDownload = detail::openMultiDownload,
                    onDismissMultiDownload = detail::dismissMultiDownload,
                    onRetryMultiDownload = detail::retryMultiDownload,
                    onToggleMultiDownloadFolder = detail::toggleMultiDownloadFolder,
                    onEnsureMultiDownloadFolderLoaded = detail::ensureMultiDownloadFolderLoaded,
                    onPerformDownloadBatch = downloads::performBatch,
                    onOpenSelectedResource = onOpenResource, onOpenReadingUnit = onOpenReadingUnit,
                    onOpenDownloadedResource = onOpenDownload,
                    managementViewModel = management, canManageSystem = canManageSystem,
                    onBookDeleted = { downloads.removeBook(bookId); onBack() },
                )
            }
        },
    )
}
