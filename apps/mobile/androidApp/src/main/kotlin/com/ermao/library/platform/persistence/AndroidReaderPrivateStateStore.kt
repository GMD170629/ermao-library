package com.ermao.library.platform.persistence

import android.content.Context
import com.ermao.library.features.reader.infrastructure.AndroidPdfRangeCache
import com.ermao.library.features.reader.infrastructure.AndroidReaderBookmarkStore
import com.ermao.library.features.reader.infrastructure.AndroidReaderNavigationCache
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressDatabase
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import java.io.File

/** Namespace-scoped Reader cleanup used for logout and authorization changes. */
internal object AndroidReaderPrivateStateStore {
    suspend fun clearNamespace(context: Context, namespace: ReaderSyncNamespace) {
        AndroidReaderProgressDatabase.clearNamespace(context, namespace)
        AndroidReaderPublicationStore.clearNamespace(context, namespace)
        AndroidReaderBookmarkStore.clearNamespace(context, namespace)
        AndroidReaderNavigationCache.clearNamespace(context, namespace)
        AndroidPdfRangeCache(File(context.cacheDir, "reader/pdf-range-v3")).clearNamespace(namespace)
    }
}
