package com.ermao.library.platform.persistence

import android.content.Context
import com.ermao.library.features.reader.infrastructure.AndroidReaderBookmarkStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderNavigationCache
import com.ermao.library.features.reader.infrastructure.AndroidReaderV5Database
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

/** Namespace-scoped Reader cleanup used for logout and authorization changes. */
internal object AndroidReaderPrivateStateStore {
    suspend fun clearNamespace(context: Context, namespace: ReaderSyncNamespace) {
        AndroidReaderV5Database.clearNamespace(context, namespace)
        AndroidReaderPublicationStore.clearNamespace(context, namespace)
        AndroidReaderBookmarkStore.clearNamespace(context, namespace)
        AndroidReaderNavigationCache.clearNamespace(context, namespace)
    }
}
