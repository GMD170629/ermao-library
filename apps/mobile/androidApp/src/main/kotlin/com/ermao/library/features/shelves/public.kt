package com.ermao.library.features.shelves

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ermao.library.features.shelves.application.ShelfCatalogViewModel
import com.ermao.library.features.shelves.ui.ShelfCatalogScreen
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.shelf.ShelfCatalogRepository
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext

@Composable
fun ShelfCatalogRoute(
    repository: ShelfCatalogRepository, contentRepository: ContentRepository, context: ContentRequestContext,
    shelfId: String? = null, onUnauthorized: () -> Unit, onBack: () -> Unit,
    onOpenShelf: (String) -> Unit, onOpenBook: (String) -> Unit,
) {
    val model: ShelfCatalogViewModel = viewModel(
        key = "shelves-${context.namespace}-$shelfId",
        factory = viewModelFactory { initializer {
            ShelfCatalogViewModel(repository, ShelfRequestContext(context.profile, context.namespace), shelfId, onUnauthorized)
        } },
    )
    val managementRevision = com.ermao.library.features.workmanagement.managementRevision()
    androidx.compose.runtime.LaunchedEffect(managementRevision) { if (managementRevision > 0) model.refresh() }
    val state by model.state.collectAsStateWithLifecycle()
    ShelfCatalogScreen(state, shelfId == null, contentRepository, context, model::search, model::selectScope,
        model::refresh, model::loadMore, onBack, onOpenShelf, onOpenBook, model::create, model::clearSaveError)
}
