package com.ermao.library.shared.modules.shelf.domain

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerProfile

data class ShelfRequestContext(
    val profile: ServerProfile,
    val namespace: PrivateDataNamespace,
) {
    init {
        require(profile.serverIdentity == namespace.serverIdentity)
    }
}

enum class ShelfKind { Static, Smart, Collection }

data class ShelfSummary(
    val id: String,
    val name: String,
    val kind: ShelfKind,
    val containsBook: Boolean,
)

enum class ShelfMembership { Add, Remove }

data class ShelfMembershipChange(
    val bookId: String,
    val shelfId: String,
    val membership: ShelfMembership,
)

enum class ShelfErrorKind {
    Unauthorized,
    Offline,
    Inaccessible,
    InvalidRequest,
    Server,
    Protocol,
}

data class ShelfError(val kind: ShelfErrorKind, val code: String)

sealed interface ShelfResult<out T> {
    data class Content<T>(val value: T) : ShelfResult<T>
    data class Failure(val error: ShelfError) : ShelfResult<Nothing>
}
