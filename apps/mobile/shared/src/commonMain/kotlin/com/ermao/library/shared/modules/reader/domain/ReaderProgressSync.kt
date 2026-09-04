package com.ermao.library.shared.modules.reader.domain

data class ReaderSyncNamespace(
    val serverIdentity: String,
    val userId: String,
    val authorizationVersion: Long,
) {
    init {
        require(serverIdentity.isNotBlank()) { "Reader sync server identity is blank" }
        require(userId.isNotBlank()) { "Reader sync user identity is blank" }
        require(authorizationVersion >= 0) { "Reader sync authorization version is negative" }
    }

    val stableKey: String
        get() = lengthPrefixed(serverIdentity, userId, authorizationVersion.toString())
}

/** Stable local identity. Authorization changes do not erase an exact location. */
data class ReaderLocalProgressIdentity(
    val namespace: ReaderSyncNamespace,
    val clientId: String,
    val bookId: String,
    val resourceId: String,
) {
    init {
        require(clientId.isNotBlank()) { "Reader local client id is blank" }
        require(bookId.isNotBlank()) { "Reader local book id is blank" }
        require(resourceId.isNotBlank()) { "Reader local resource id is blank" }
    }

    val stableKey: String
        get() = lengthPrefixed(
            namespace.serverIdentity,
            namespace.userId,
            clientId,
            bookId,
            resourceId,
        )
}

data class ReaderProgressSyncTarget(
    val namespace: ReaderSyncNamespace,
    val bookId: String,
    val resourceId: String,
    val sourceFormat: ReaderFormat,
) {
    init {
        require(bookId.isNotBlank()) { "Reader sync book id is blank" }
        require(resourceId.isNotBlank()) { "Reader sync resource id is blank" }
    }

    val slotKey: String
        get() = lengthPrefixed(namespace.stableKey, resourceId)
}

private fun lengthPrefixed(vararg values: String): String = buildString {
    values.forEach { value ->
        append(value.length)
        append(':')
        append(value)
    }
}
