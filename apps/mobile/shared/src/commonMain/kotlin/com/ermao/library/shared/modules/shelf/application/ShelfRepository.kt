package com.ermao.library.shared.modules.shelf.application

import com.ermao.library.shared.modules.shelf.domain.ShelfMembershipChange
import com.ermao.library.shared.modules.shelf.domain.ShelfRequestContext
import com.ermao.library.shared.modules.shelf.domain.ShelfResult
import com.ermao.library.shared.modules.shelf.domain.ShelfSummary

interface ShelfRepository {
    suspend fun loadShelves(
        context: ShelfRequestContext,
        bookId: String,
    ): ShelfResult<List<ShelfSummary>>

    suspend fun updateMembership(
        context: ShelfRequestContext,
        change: ShelfMembershipChange,
    ): ShelfResult<Unit>
}
