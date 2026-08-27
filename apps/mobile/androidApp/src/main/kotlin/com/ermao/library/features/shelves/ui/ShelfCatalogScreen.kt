package com.ermao.library.features.shelves.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.content.CatalogBookCover
import com.ermao.library.features.shelves.application.ShelfCatalogUiState
import com.ermao.library.features.shelves.application.ShelfLoadState
import com.ermao.library.features.shelves.application.ShelfSaveState
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.shared.modules.shelf.CreateShelfInput
import com.ermao.library.shared.modules.shelf.ShelfCatalogEntry
import com.ermao.library.shared.modules.shelf.ShelfCatalogScope
import com.ermao.library.shared.modules.shelf.ShelfKind
import com.ermao.library.shared.modules.shelf.ShelfErrorKind
import com.ermao.library.shared.modules.shelf.catalogPreview
import com.ermao.library.ui.components.WarmPageNavigationAction
import com.ermao.library.ui.components.WarmPageScaffold
import com.ermao.library.ui.components.WarmPageSearchField
import com.ermao.library.ui.components.WarmPageTopBarAction
import com.ermao.library.ui.components.WarmPageTopBarRole
import com.ermao.library.ui.theme.WarmPageThemeValues
import java.text.NumberFormat
import androidx.compose.ui.platform.LocalConfiguration

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShelfCatalogScreen(
    state: ShelfCatalogUiState,
    isRoot: Boolean,
    repository: ContentRepository,
    context: ContentRequestContext,
    onSearch: (String) -> Unit,
    onScope: (ShelfCatalogScope) -> Unit,
    onRefresh: () -> Unit,
    onLoadMore: () -> Unit,
    onBack: () -> Unit,
    onOpenShelf: (String) -> Unit,
    onOpenBook: (String) -> Unit,
    onCreate: (CreateShelfInput, (String) -> Unit) -> Unit,
    onClearSaveError: () -> Unit,
) {
    val theme = WarmPageThemeValues
    val ready = state.content as? ShelfLoadState.Ready
    val detail = ready?.detail?.shelf
    val showsShelves = isRoot || detail?.kind == ShelfKind.Collection
    val scopeDescription = stringResource(R.string.shelves_scope)
    var showsCreate by rememberSaveable { mutableStateOf(false) }
    WarmPageScaffold(
        role = if (isRoot) WarmPageTopBarRole.Root else WarmPageTopBarRole.Detail,
        title = detail?.name ?: stringResource(R.string.tab_shelves),
        navigation = if (isRoot) null else WarmPageNavigationAction(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.shelves_back), onBack),
        actions = listOf(if (isRoot) {
            WarmPageTopBarAction(Icons.Default.Add, stringResource(R.string.shelves_create), enabled = ready != null) {
                onClearSaveError(); showsCreate = true
            }
        } else WarmPageTopBarAction(Icons.Default.Refresh, stringResource(R.string.shelves_refresh), onClick = onRefresh)),
        modifier = Modifier.testTag(if (isRoot) "shelves-root" else "shelf-detail"),
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp)) {
            if (showsShelves) {
                WarmPageSearchField(
                    value = state.query, placeholder = stringResource(if (isRoot) R.string.shelves_search else R.string.shelves_search_collection),
                    onValueChange = onSearch, onClear = { onSearch("") }, clearLabel = stringResource(R.string.clear_action),
                    modifier = Modifier.testTag("shelves-search"),
                )
            }
            if (isRoot) Row(Modifier.fillMaxWidth().semantics { contentDescription = scopeDescription }, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ShelfCatalogScope.entries.forEach { scope ->
                    FilterChip(
                        selected = state.scope == scope, onClick = { onScope(scope) },
                        label = { Text(stringResource(scope.label()), modifier = Modifier.padding(horizontal = 8.dp)) },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = theme.colors.accentSoft,
                            selectedLabelColor = theme.colors.actionAccent,
                            containerColor = theme.colors.canvas,
                        ), modifier = Modifier.weight(1f).heightIn(min = 48.dp).testTag("shelves-scope-${scope.name}"),
                    )
                }
            } else if (detail != null) {
                Text(shelfCountText(detail), style = theme.typography.callout, color = theme.colors.textSecondary, modifier = Modifier.padding(vertical = 12.dp))
            }
            HorizontalDivider(color = theme.colors.divider)
            PullToRefreshBox(isRefreshing = false, onRefresh = onRefresh, modifier = Modifier.weight(1f)) {
                LazyColumn(Modifier.fillMaxSize()) {
                    when (val content = state.content) {
                        ShelfLoadState.Loading -> item {
                            Row(Modifier.fillMaxWidth().padding(32.dp), horizontalArrangement = Arrangement.Center) {
                                CircularProgressIndicator(Modifier.size(24.dp))
                            }
                        }
                        is ShelfLoadState.Failed -> item {
                            ShelfMessage(
                                stringResource(if (content.error.kind == ShelfErrorKind.Inaccessible) R.string.shelves_inaccessible else R.string.shelves_error),
                                stringResource(R.string.shelves_error_message), onRefresh,
                            )
                        }
                        is ShelfLoadState.Ready -> if (showsShelves) {
                            if (state.visibleShelves.isEmpty()) item {
                                ShelfMessage(
                                    stringResource(if (state.query.isBlank()) R.string.shelves_empty else R.string.shelves_no_results),
                                    stringResource(if (state.query.isBlank()) R.string.shelves_empty_message else R.string.shelves_no_results_message),
                                )
                            }
                            items(state.visibleShelves, key = { it.id }) { shelf ->
                                ShelfCatalogRow(shelf, content.catalog, repository, context) { onOpenShelf(shelf.id) }
                                HorizontalDivider(color = theme.colors.divider)
                            }
                        } else {
                            val page = content.detail
                            if (page?.shelf?.books.isNullOrEmpty()) item {
                                ShelfMessage(stringResource(R.string.shelves_empty_books), stringResource(R.string.shelves_empty_books_message))
                            }
                            items(page?.shelf?.books.orEmpty(), key = { it.id }) { book ->
                                Row(
                                    Modifier.fillMaxWidth().clickable(role = Role.Button) { onOpenBook(book.id) }.padding(vertical = 16.dp),
                                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp),
                                ) {
                                    CatalogBookCover(book.id, book.title, book.coverUrl, repository, context, Modifier.width(64.dp))
                                    Column(Modifier.weight(1f)) {
                                        Text(book.title, style = theme.typography.headline, maxLines = 3, overflow = TextOverflow.Ellipsis)
                                        book.author?.let { Text(it, style = theme.typography.callout, color = theme.colors.textSecondary) }
                                    }
                                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = theme.colors.textSecondary)
                                }
                                HorizontalDivider(color = theme.colors.divider)
                            }
                            if (page != null && page.page < page.totalPages) item {
                                if (state.loadingMore) CircularProgressIndicator(Modifier.padding(16.dp).size(24.dp))
                                else TextButton(onClick = onLoadMore, modifier = Modifier.fillMaxWidth()) {
                                    Text(stringResource(if (state.paginationError == null) R.string.shelves_load_more else R.string.shelves_load_more_retry))
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    if (showsCreate && ready != null) ShelfCreateSheet(
        catalog = ready.catalog, saveState = state.saveState,
        onDismiss = { showsCreate = false; onClearSaveError() },
        onSubmit = { input -> onCreate(input) { id -> showsCreate = false; onOpenShelf(id) } },
    )
}

@Composable
private fun ShelfCatalogRow(
    shelf: ShelfCatalogEntry, catalog: List<ShelfCatalogEntry>, repository: ContentRepository,
    context: ContentRequestContext, onClick: () -> Unit,
) {
    val theme = WarmPageThemeValues
    val previewCount = if (LocalDensity.current.fontScale > 1.3f) 1 else 3
    Row(
        Modifier.fillMaxWidth().heightIn(min = 116.dp).clickable(role = Role.Button, onClick = onClick).padding(vertical = 20.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(shelf.name, style = theme.typography.headline, maxLines = 3, overflow = TextOverflow.Ellipsis)
            Text(shelfCountText(shelf), style = theme.typography.caption, color = theme.colors.textSecondary)
            if (shelf.kind == ShelfKind.Smart) Text(
                shelf.description?.takeIf { it.isNotBlank() } ?: stringResource(if (shelf.rulesSupported) R.string.shelves_smart_hint else R.string.shelves_rules_unsupported),
                style = theme.typography.caption, color = theme.colors.textSecondary, maxLines = 2, overflow = TextOverflow.Ellipsis,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.clearAndSetSemantics {}) {
            catalogPreview(shelf, catalog).take(previewCount).forEach { book ->
                CatalogBookCover(book.id, book.title, book.coverUrl, repository, context, Modifier.width(52.dp))
            }
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = theme.colors.textSecondary, modifier = Modifier.size(20.dp))
    }
}

@Composable
private fun shelfCountText(shelf: ShelfCatalogEntry): String {
    val locale = LocalConfiguration.current.locales[0]
    val count = NumberFormat.getIntegerInstance(locale).format(shelf.count)
    return stringResource(when (shelf.kind) {
        ShelfKind.Collection -> R.string.shelves_count_collection
        ShelfKind.Smart -> R.string.shelves_count_smart
        ShelfKind.Static -> R.string.shelves_count_books
    }, count)
}

private fun ShelfCatalogScope.label(): Int = when (this) {
    ShelfCatalogScope.All -> R.string.shelves_all
    ShelfCatalogScope.Shelves -> R.string.tab_shelves
    ShelfCatalogScope.Collections -> R.string.shelves_collections
}

@Composable
private fun ShelfMessage(title: String, message: String, retry: (() -> Unit)? = null) {
    val theme = WarmPageThemeValues
    Column(Modifier.fillMaxWidth().padding(vertical = 32.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(title, style = theme.typography.headline)
        Text(message, style = theme.typography.callout, color = theme.colors.textSecondary)
        if (retry != null) TextButton(onClick = retry) { Text(stringResource(R.string.retry_action)) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ShelfCreateSheet(
    catalog: List<ShelfCatalogEntry>, saveState: ShelfSaveState,
    onDismiss: () -> Unit, onSubmit: (CreateShelfInput) -> Unit,
) {
    var name by rememberSaveable { mutableStateOf("") }
    var description by rememberSaveable { mutableStateOf("") }
    var collection by rememberSaveable { mutableStateOf(false) }
    var members by rememberSaveable { mutableStateOf(emptyList<String>()) }
    val saving = saveState == ShelfSaveState.Saving
    ModalBottomSheet(onDismissRequest = { if (!saving) onDismiss() }) {
        LazyColumn(Modifier.padding(horizontal = 24.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(stringResource(R.string.shelves_create), style = WarmPageThemeValues.typography.headline, modifier = Modifier.weight(1f))
                    TextButton(onClick = onDismiss, enabled = !saving) { Text(stringResource(R.string.cancel_action)) }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = !collection, enabled = !saving, onClick = { collection = false }, label = { Text(stringResource(R.string.tab_shelves)) })
                    FilterChip(selected = collection, enabled = !saving, onClick = { collection = true }, label = { Text(stringResource(R.string.shelves_collections)) })
                }
            }
            item { OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.shelves_name)) }, singleLine = true, enabled = !saving, modifier = Modifier.fillMaxWidth()) }
            item { OutlinedTextField(description, { description = it }, label = { Text(stringResource(R.string.shelves_description)) }, enabled = !saving, modifier = Modifier.fillMaxWidth()) }
            if (collection) {
                item { Text(stringResource(R.string.shelves_choose_members)) }
                items(catalog.filter { it.kind != ShelfKind.Collection }, key = { it.id }) { shelf ->
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = shelf.id in members, enabled = !saving, onCheckedChange = { checked -> members = if (checked) members + shelf.id else members - shelf.id })
                        Text(shelf.name)
                    }
                }
            }
            if (saveState is ShelfSaveState.Failed) item { Text(stringResource(R.string.shelves_create_failed)) }
            item {
                TextButton(enabled = !saving && name.isNotBlank(), modifier = Modifier.fillMaxWidth(), onClick = {
                    onSubmit(CreateShelfInput(name.trim(), description.trim(), if (collection) ShelfKind.Collection else ShelfKind.Static, if (collection) members else emptyList()))
                }) {
                    if (saving) CircularProgressIndicator(Modifier.size(20.dp)) else Text(stringResource(R.string.shelves_create))
                }
            }
        }
    }
}
