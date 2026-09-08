package com.ermao.library.platform.persistence

import android.content.Context
import com.ermao.library.features.reader.infrastructure.AndroidReaderBookmarkStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderNavigationCache
import com.ermao.library.features.reader.infrastructure.AndroidReaderV5Database
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

/** Namespace-scoped Reader cleanup used for logout and authorization changes. */
internal object AndroidReaderPrivateStateStore {
    /** Clears the current device's locator and pending upload for one resource. */
    suspend fun deletePosition(
        context: Context,
        namespace: ReaderSyncNamespace,
        clientId: String,
        resourceId: String,
    ) {
        AndroidReaderV5Database.deleteResourcePositions(
            context = context,
            namespace = namespace,
            clientId = clientId,
            resourceId = resourceId,
        )
    }

    /** Clears all current-device resource slots belonging to one book. */
    suspend fun deleteBookPositions(
        context: Context,
        namespace: ReaderSyncNamespace,
        clientId: String,
        bookId: String,
    ) {
        AndroidReaderV5Database.deleteBookPositions(
            context = context,
            namespace = namespace,
            clientId = clientId,
            bookId = bookId,
        )
    }

    suspend fun clearNamespace(context: Context, namespace: ReaderSyncNamespace) {
        AndroidReaderV5Database.clearNamespace(context, namespace)
        AndroidReaderPublicationStore.clearNamespace(context, namespace)
        AndroidReaderBookmarkStore.clearNamespace(context, namespace)
        AndroidReaderNavigationCache.clearNamespace(context, namespace)
    }
}
