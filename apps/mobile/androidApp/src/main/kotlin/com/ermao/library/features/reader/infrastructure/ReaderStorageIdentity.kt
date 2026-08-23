package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

/**
 * Stable private-storage ownership key for one server/user account.
 *
 * Authorization generations deliberately do not participate in this key: a
 * logout or auth change must be able to evict every generation belonging to
 * the account without touching another account on the same device.
 */
internal fun readerAccountStorageKey(namespace: ReaderSyncNamespace): String = buildString {
    appendLengthPrefixed(namespace.serverIdentity)
    appendLengthPrefixed(namespace.userId)
}

private fun StringBuilder.appendLengthPrefixed(value: String) {
    append(value.length)
    append(':')
    append(value)
}
