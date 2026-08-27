package com.ermao.library.shared.modules.shelf.application

import com.ermao.library.shared.modules.shelf.domain.CreateShelfInput
import com.ermao.library.shared.modules.shelf.domain.ShelfCatalogEntry
import com.ermao.library.shared.modules.shelf.domain.ShelfCatalogPage
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfResult

interface ShelfCatalogRepository {
    suspend fun loadCatalog(context: ShelfRequestContext): ShelfResult<List<ShelfCatalogEntry>>
    /** The server's stable member/book order is preserved; page size is bounded to 24. */
    suspend fun loadPage(context: ShelfRequestContext, shelfId: String, page: Int): ShelfResult<ShelfCatalogPage>
    /** Explicit user submission only. No optimistic publication; reload after server acknowledgement. */
    suspend fun createShelf(context: ShelfRequestContext, input: CreateShelfInput): ShelfResult<String>
}
