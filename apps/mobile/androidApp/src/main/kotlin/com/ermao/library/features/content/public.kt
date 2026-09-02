package com.ermao.library.features.content

import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import com.ermao.library.shared.modules.library.ContentRepository
import com.ermao.library.shared.modules.library.ContentRequestContext

/** Public, authenticated compact artwork boundary for catalog consumers. */
@Composable
fun CatalogBookCover(
    id: String,
    title: String,
    coverUrl: String,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
    managementEnabled: Boolean = true,
) {
    key(context.namespace, id, coverUrl) {
        val artwork: @Composable () -> Unit = { com.ermao.library.features.content.ui.ContentCover(
            contentId = id, title = title, coverUrl = coverUrl, repository = repository,
            context = context, role = com.ermao.library.features.content.ui.CoverRole.Compact, modifier = if (managementEnabled) Modifier else modifier,
        ) }
        if (managementEnabled) com.ermao.library.features.workmanagement.ManageableBookCover(id, title, modifier, content = artwork) else artwork()
    }
}

/** Public authenticated artwork boundary for feature-owned cover surfaces. */
@Composable
fun AuthenticatedBookArtwork(
    id: String,
    title: String,
    coverUrl: String,
    repository: ContentRepository,
    context: ContentRequestContext,
    modifier: Modifier = Modifier,
) {
    key(context.namespace, id, coverUrl) {
        com.ermao.library.features.content.ui.AuthenticatedCoverArtwork(
            contentId = id,
            title = title,
            coverUrl = coverUrl,
            repository = repository,
            context = context,
            modifier = modifier,
        )
    }
}
