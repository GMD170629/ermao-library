@file:Suppress("PARAMETER_NAME_CHANGED_ON_OVERRIDE")

package com.ermao.library.features.reader.infrastructure

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.core.database.sqlite.transaction
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderPositionDurableState
import com.ermao.library.shared.modules.reader.ReaderPositionJson
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.ReaderPositionPresentationSnapshot
import com.ermao.library.shared.modules.reader.ReaderPositionSyncStateJson
import com.ermao.library.shared.modules.reader.ReaderPositionSyncStateStore
import com.ermao.library.shared.modules.reader.ReaderPositionSyncingStore
import com.ermao.library.shared.modules.reader.ReaderPositionWriteResponse
import com.ermao.library.shared.modules.reader.ReaderProgressMutationV5
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV5
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * The production Reader v5 store.
 *
 * This database is intentionally a new SQLite namespace. Its schema has no
 * predecessor and therefore has no upgrade, migration, or legacy-data scan.
 * This is the only production Reader position database.  It has no predecessor
 * and is never opened through an older Reader database/helper.
 */
internal class AndroidReaderV5Database(
    context: Context,
    private val identity: ReaderLocalProgressIdentity,
    databaseName: String = DATABASE_NAME,
) : ReaderPositionSyncStateStore {
    private val positionCodec = ReaderPositionJson()
    private val syncCodec = ReaderPositionSyncStateJson()
    private val database = ReaderV5DatabaseHelper(context.applicationContext, databaseName)
    private val mutex = Mutex()

    override suspend fun loadPosition(resourceId: String): ReaderPositionLocalState? {
        require(resourceId == identity.resourceId) {
            "Reader v5 position resource does not match its exact identity"
        }
        return io {
            database.readableDatabase.query(
                POSITION_TABLE,
                arrayOf(POSITION_DOCUMENT),
                "$POSITION_OWNER_KEY = ?",
                arrayOf(positionStorageKey()),
                null,
                null,
                null,
                "1",
            ).use { cursor ->
                if (!cursor.moveToFirst()) {
                    null
                } else {
                    positionCodec.decode(cursor.getString(0)).also {
                        require(
                            it.resourceId == resourceId && it.clientId == identity.clientId,
                        ) { "Reader v5 position database identity mismatch" }
                    }
                }
            }
        }
    }

    override suspend fun savePosition(position: ReaderPositionLocalState): Unit = io {
        writePosition(database.writableDatabase, position)
    }

    override suspend fun deletePosition(resourceId: String) {
        require(resourceId == identity.resourceId) {
            "Reader v5 position resource does not match its exact identity"
        }
        io {
            database.writableDatabase.transaction {
                delete(POSITION_TABLE, "$POSITION_OWNER_KEY = ?", arrayOf(positionStorageKey()))
                delete(POSITION_SYNC_TABLE, "$POSITION_SYNC_OWNER_KEY = ?", arrayOf(positionSyncStorageKey()))
            }
        }
    }

    override suspend fun loadPositionSyncState(): ReaderPositionDurableState = io {
        database.readableDatabase.query(
            POSITION_SYNC_TABLE,
            arrayOf(POSITION_SYNC_DOCUMENT),
            "$POSITION_SYNC_OWNER_KEY = ?",
            arrayOf(positionSyncStorageKey()),
            null,
            null,
            null,
            "1",
        ).use { cursor ->
            if (!cursor.moveToFirst()) ReaderPositionDurableState()
            else syncCodec.decode(cursor.getString(0))
        }
    }

    override suspend fun commitPositionAndPending(
        position: ReaderPositionLocalState,
        pending: ReaderProgressMutationV5,
    ): Unit = io {
        require(position.resourceId == pending.resourceId)
        require(position.clientId == pending.clientId)
        database.writableDatabase.transaction {
            writePosition(database.writableDatabase, position)
            val current = readPositionSyncState(database.writableDatabase)
            writePositionSyncState(
                database.writableDatabase,
                current.copy(pending = pending, terminalFailureCode = null),
            )
        }
    }

    override suspend fun acknowledgePosition(
        mutationId: String,
        response: ReaderPositionWriteResponse,
    ): Unit = io {
        database.writableDatabase.transaction {
            val current = readPositionSyncState(database.writableDatabase)
            if (current.pending?.mutationId != mutationId) return@transaction
            writePositionSyncState(
                database.writableDatabase,
                current.copy(
                    confirmedRevision = maxOf(
                        current.confirmedRevision,
                        response.acceptedRevision,
                        response.currentSnapshot.revision,
                    ),
                    pending = null,
                    terminalFailureCode = null,
                ),
            )
        }
    }

    override suspend fun acceptRemotePosition(
        position: ReaderPositionLocalState,
        snapshot: ReaderProgressSnapshotV5,
    ): Unit = io {
        require(position.resourceId == snapshot.resourceId)
        database.writableDatabase.transaction {
            writePosition(database.writableDatabase, position)
            writePositionSyncState(
                database.writableDatabase,
                ReaderPositionDurableState(confirmedRevision = snapshot.revision),
            )
        }
    }

    override suspend fun recordPositionTerminalFailure(
        mutationId: String,
        failureCode: String,
    ): Unit = io {
        database.writableDatabase.transaction {
            val current = readPositionSyncState(database.writableDatabase)
            if (current.pending?.mutationId == mutationId) {
                writePositionSyncState(
                    database.writableDatabase,
                    current.copy(terminalFailureCode = failureCode),
                )
            }
        }
    }

    internal fun close() = database.close()

    private fun writePosition(database: SQLiteDatabase, position: ReaderPositionLocalState) {
        require(
            position.resourceId == identity.resourceId && position.clientId == identity.clientId,
        ) { "Reader v5 position does not match its exact identity" }
        val values = ContentValues().apply {
            put(POSITION_OWNER_KEY, positionStorageKey())
            put(POSITION_DOCUMENT, positionCodec.encode(position))
        }
        database.insertWithOnConflict(
            POSITION_TABLE,
            null,
            values,
            SQLiteDatabase.CONFLICT_REPLACE,
        ).also { rowId -> check(rowId != -1L) { "Reader v5 position save failed" } }
    }

    private fun readPositionSyncState(database: SQLiteDatabase): ReaderPositionDurableState =
        database.query(
            POSITION_SYNC_TABLE,
            arrayOf(POSITION_SYNC_DOCUMENT),
            "$POSITION_SYNC_OWNER_KEY = ?",
            arrayOf(positionSyncStorageKey()),
            null,
            null,
            null,
            "1",
        ).use { cursor ->
            if (!cursor.moveToFirst()) ReaderPositionDurableState()
            else syncCodec.decode(cursor.getString(0))
        }

    private fun writePositionSyncState(database: SQLiteDatabase, state: ReaderPositionDurableState) {
        val values = ContentValues().apply {
            put(POSITION_SYNC_OWNER_KEY, positionSyncStorageKey())
            put(POSITION_SYNC_DOCUMENT, syncCodec.encode(state))
        }
        database.insertWithOnConflict(
            POSITION_SYNC_TABLE,
            null,
            values,
            SQLiteDatabase.CONFLICT_REPLACE,
        ).also { rowId -> check(rowId != -1L) { "Reader v5 sync state save failed" } }
    }

    private fun positionStorageKey(): String =
        "${readerAccountStorageKey(identity.namespace)}:${identity.stableKey}"

    private fun positionSyncStorageKey(): String =
        "${readerAccountStorageKey(identity.namespace)}:${identity.stableKey}"

    private suspend fun <T> io(block: () -> T): T = mutex.withLock {
        withContext(Dispatchers.IO) { block() }
    }

    private class ReaderV5DatabaseHelper(context: Context, databaseName: String) :
        SQLiteOpenHelper(context, databaseName, null, DATABASE_VERSION) {
        override fun onCreate(database: SQLiteDatabase) {
            database.execSQL(
                "CREATE TABLE $POSITION_TABLE (" +
                    "$POSITION_OWNER_KEY TEXT PRIMARY KEY NOT NULL," +
                    "$POSITION_DOCUMENT TEXT NOT NULL)",
            )
            database.execSQL(
                "CREATE TABLE $POSITION_SYNC_TABLE (" +
                    "$POSITION_SYNC_OWNER_KEY TEXT PRIMARY KEY NOT NULL," +
                    "$POSITION_SYNC_DOCUMENT TEXT NOT NULL)",
            )
        }

        override fun onUpgrade(database: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            throw IllegalStateException(
                "Reader v5 database has no migration ($oldVersion to $newVersion)",
            )
        }
    }

    companion object {
        internal const val DATABASE_NAME = "reader-position-v5.db"
        internal const val DATABASE_VERSION = 1
        internal const val POSITION_TABLE = "reader_position"
        internal const val POSITION_OWNER_KEY = "owner_key"
        internal const val POSITION_DOCUMENT = "document_json"
        internal const val POSITION_SYNC_TABLE = "reader_position_sync"
        internal const val POSITION_SYNC_OWNER_KEY = "owner_key"
        internal const val POSITION_SYNC_DOCUMENT = "document_json"

        /**
         * Returns only the presentation sibling of each current-device v5
         * position.  The opaque Locator is decoded only to validate the v5
         * document and is never returned to library surfaces.
         */
        internal suspend fun loadPresentationSnapshots(
            context: Context,
            namespace: com.ermao.library.shared.modules.reader.ReaderSyncNamespace,
            clientId: String,
            bookIds: Set<String> = emptySet(),
        ): List<ReaderPositionPresentationSnapshot> {
            require(clientId.isNotBlank()) { "Reader presentation client id is blank" }
            require(bookIds.all(String::isNotBlank)) { "Reader presentation book id is blank" }
            val helper = ReaderV5DatabaseHelper(context.applicationContext, DATABASE_NAME)
            val codec = ReaderPositionJson()
            val prefix = "${readerAccountStorageKey(namespace)}:${lengthPrefixed(
                namespace.serverIdentity,
                namespace.userId,
                clientId,
            )}"
            return try {
                withContext(Dispatchers.IO) {
                    helper.readableDatabase.query(
                        POSITION_TABLE,
                        arrayOf(POSITION_OWNER_KEY, POSITION_DOCUMENT),
                        null,
                        null,
                        null,
                        null,
                        null,
                        null,
                    ).use { cursor ->
                        buildList {
                            while (cursor.moveToNext()) {
                                val ownerKey = cursor.getString(0)
                                if (!ownerKey.startsWith(prefix)) continue
                                val owner = decodeOwnerSuffix(ownerKey.removePrefix(prefix)) ?: continue
                                if (bookIds.isNotEmpty() && owner.first !in bookIds) continue
                                runCatching { codec.decode(cursor.getString(1)) }
                                    .getOrNull()
                                    ?.takeIf { it.clientId == clientId && it.resourceId == owner.second }
                                    ?.let { state ->
                                        add(
                                            ReaderPositionPresentationSnapshot(
                                                bookId = owner.first,
                                                resourceId = state.resourceId,
                                                capturedAtEpochMillis = state.capturedAtEpochMillis,
                                                presentation = state.position.presentation,
                                            ),
                                        )
                                    }
                            }
                        }.sortedWith(
                            compareByDescending<ReaderPositionPresentationSnapshot> {
                                it.capturedAtEpochMillis
                            }.thenBy { it.resourceId },
                        )
                    }
                }
            } finally {
                helper.close()
            }
        }

        private fun lengthPrefixed(vararg values: String): String = buildString {
            values.forEach { value ->
                append(value.length)
                append(':')
                append(value)
            }
        }

        private fun decodeOwnerSuffix(value: String): Pair<String, String>? {
            val book = readLengthPrefixed(value, 0) ?: return null
            val resource = readLengthPrefixed(value, book.second) ?: return null
            return (book.first to resource.first).takeIf { resource.second == value.length }
        }

        private fun readLengthPrefixed(value: String, start: Int): Pair<String, Int>? {
            if (start !in 0..value.length) return null
            val separator = value.indexOf(':', start)
            if (separator <= start) return null
            val length = value.substring(start, separator).toIntOrNull() ?: return null
            if (length < 0) return null
            val end = separator + 1 + length
            if (end > value.length) return null
            return value.substring(separator + 1, end) to end
        }

        /** Deletes only v5 rows for this account; the retired database is untouched. */
        internal suspend fun clearNamespace(context: Context, namespace: com.ermao.library.shared.modules.reader.ReaderSyncNamespace) {
            val helper = ReaderV5DatabaseHelper(context.applicationContext, DATABASE_NAME)
            try {
                withContext(Dispatchers.IO) {
                    val prefix = "${readerAccountStorageKey(namespace)}:"
                    helper.writableDatabase.transaction {
                        deleteKeysWithPrefix(POSITION_TABLE, POSITION_OWNER_KEY, prefix)
                        deleteKeysWithPrefix(POSITION_SYNC_TABLE, POSITION_SYNC_OWNER_KEY, prefix)
                    }
                }
            } finally {
                helper.close()
            }
        }

        private fun SQLiteDatabase.deleteKeysWithPrefix(table: String, column: String, prefix: String) {
            val keys = query(table, arrayOf(column), null, null, null, null, null, null).use { cursor ->
                buildList {
                    while (cursor.moveToNext()) {
                        cursor.getString(0)?.takeIf { it.startsWith(prefix) }?.let(::add)
                    }
                }
            }
            keys.forEach { key -> delete(table, "$column = ?", arrayOf(key)) }
        }
    }
}

/** Public Reader-module query for durable presentation-only projections. */
class AndroidReaderV5PresentationQuery(private val context: Context) {
    suspend fun load(
        namespace: com.ermao.library.shared.modules.reader.ReaderSyncNamespace,
        clientId: String,
        bookIds: Set<String> = emptySet(),
    ): List<ReaderPositionPresentationSnapshot> = AndroidReaderV5Database.loadPresentationSnapshots(
        context = context,
        namespace = namespace,
        clientId = clientId,
        bookIds = bookIds,
    )
}

/** Local-only v5 store for an explicitly supplied local Reader source. */
internal class AndroidReaderV5LocalStore(
    private val stateStore: ReaderPositionSyncStateStore,
) : ReaderPositionSyncingStore {
    override suspend fun load(resourceId: String): ReaderPositionLocalState? =
        stateStore.loadPosition(resourceId)

    override suspend fun save(position: ReaderPositionLocalState) {
        stateStore.savePosition(position)
    }

    override suspend fun delete(resourceId: String) {
        stateStore.deletePosition(resourceId)
    }

    override suspend fun awaitPendingUpload() = Unit

    override suspend fun retryPendingUpload() = Unit

    override suspend fun syncState(): ReaderPositionDurableState =
        stateStore.loadPositionSyncState()
}
