package com.ermao.library.features.reader

import android.content.Context
import com.ermao.library.features.reader.infrastructure.AndroidReaderDeviceIdentity
import com.ermao.library.features.reader.infrastructure.AndroidReaderV5Database
import com.ermao.library.shared.modules.reader.LocalReaderSource
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.ReaderPositionReport
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

/**
 * Test-only access to the local-source Reader v5 namespace used by
 * [com.ermao.library.features.reader.presentation.ReaderActivity].
 *
 * Tests intentionally open the v5 store rather than reviving the retired v4
 * progress store. The helper keeps the local identity construction in one
 * place while leaving production storage wiring untouched.
 */
internal suspend fun loadLocalReaderV5Position(
    context: Context,
    source: LocalReaderSource,
): ReaderPositionLocalState? = withLocalReaderV5Database(context, source) {
    loadPosition(source.resourceId)
}

internal suspend fun deleteLocalReaderV5Position(
    context: Context,
    source: LocalReaderSource,
) {
    withLocalReaderV5Database(context, source) {
        deletePosition(source.resourceId)
    }
}

internal suspend fun saveLocalReaderV5Position(
    context: Context,
    source: LocalReaderSource,
    position: ReaderPositionReport,
    capturedAtEpochMillis: Long,
) {
    withLocalReaderV5Database(context, source) {
        savePosition(
            ReaderPositionLocalState(
                resourceId = source.resourceId,
                clientId = AndroidReaderDeviceIdentity(context).stableDeviceId(),
                capturedAtEpochMillis = capturedAtEpochMillis,
                position = position,
            ),
        )
    }
}

private suspend fun <T> withLocalReaderV5Database(
    context: Context,
    source: LocalReaderSource,
    block: suspend AndroidReaderV5Database.() -> T,
): T {
    val database = AndroidReaderV5Database(context, localReaderV5Identity(context, source))
    return try {
        database.block()
    } finally {
        database.close()
    }
}

private fun localReaderV5Identity(
    context: Context,
    source: LocalReaderSource,
): ReaderLocalProgressIdentity = ReaderLocalProgressIdentity(
    namespace = ReaderSyncNamespace("local-reader", "local-user", 0),
    clientId = AndroidReaderDeviceIdentity(context).stableDeviceId(),
    bookId = source.bookId ?: "local-${source.resourceId}",
    resourceId = source.resourceId,
)
