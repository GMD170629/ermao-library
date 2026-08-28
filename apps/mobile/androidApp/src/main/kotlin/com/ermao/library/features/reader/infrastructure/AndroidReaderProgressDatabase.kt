@file:Suppress("PARAMETER_NAME_CHANGED_ON_OVERRIDE")

package com.ermao.library.features.reader.infrastructure

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.core.database.sqlite.transaction
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressDurableState
import com.ermao.library.shared.modules.reader.ReaderProgressJson
import com.ermao.library.shared.modules.reader.ReaderProgressStore
import com.ermao.library.shared.modules.reader.ReaderProgressMutation
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV4
import com.ermao.library.shared.modules.reader.ReaderProgressSyncStateJson
import com.ermao.library.shared.modules.reader.ReaderProgressSyncStateStore
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** Exact progress and the latest-only Reader v4 pending mutation in one SQLite database. */
internal class AndroidReaderProgressDatabase(
    context: Context,
    private val identity: ReaderLocalProgressIdentity,
    private val progressCodec: ReaderProgressJson = ReaderProgressJson(),
    private val syncCodec: ReaderProgressSyncStateJson = ReaderProgressSyncStateJson(),
    private val legacyProgressStore: ReaderProgressStore? = AndroidReaderProgressStore(context, identity.namespace),
    databaseName: String = DATABASE_NAME,
) : ReaderProgressSyncStateStore {
    private val database = ReaderDatabaseHelper(context.applicationContext, databaseName)
    private val mutex = Mutex()

    override suspend fun load(resourceId: String): ReaderProgress? {
        require(resourceId == identity.resourceId) { "Reader progress resource does not match its exact identity" }
        val stored = io {
            val writable = database.writableDatabase
            readByKey(writable, progressStorageKey(), resourceId)
                ?: migrateAuthorizationScopedProgress(writable, resourceId)
        }
        if (stored != null) return stored

        // Import only a validated document belonging to this client/resource.
        // Unknown historical representations remain on disk for recovery.
        val legacy = legacyProgressStore?.load(resourceId) ?: return null
        if (!matchesIdentity(legacy)) return null
        save(legacy)
        legacyProgressStore.delete(resourceId)
        return legacy
    }

    override suspend fun save(progress: ReaderProgress): Unit = io {
        write(database.writableDatabase, progress)
    }

    override suspend fun loadSyncState(): ReaderProgressDurableState = io {
        readSyncState(database.readableDatabase)
    }

    override suspend fun commitProgressAndPending(
        progress: ReaderProgress,
        pending: ReaderProgressMutation,
    ): Unit = io {
        require(progress.resourceId == pending.resourceId)
        val writable = database.writableDatabase
        writable.transaction {
            write(writable, progress)
            val current = readSyncState(writable)
            writeSyncState(
                writable,
                current.copy(pending = pending, terminalFailureCode = null),
            )
        }
    }

    override suspend fun acknowledge(
        mutationId: String,
        snapshot: ReaderProgressSnapshotV4,
    ): Unit = io {
        val writable = database.writableDatabase
        writable.transaction {
            val current = readSyncState(writable)
            val rebased = current.pending?.let { pending ->
                if (pending.mutationId == mutationId) null else pending.copy(baseRevision = snapshot.revision)
            }
            writeSyncState(
                writable,
                current.copy(
                    confirmedRevision = maxOf(current.confirmedRevision, snapshot.revision),
                    pending = rebased,
                    terminalFailureCode = null,
                ),
            )
        }
    }

    override suspend fun discardPendingAfterConflict(mutationId: String, serverRevision: Long): Unit = io {
        val writable = database.writableDatabase
        writable.transaction {
            val current = readSyncState(writable)
            val rebased = current.pending?.let { pending ->
                if (pending.mutationId == mutationId) null else pending.copy(baseRevision = serverRevision)
            }
            writeSyncState(
                writable,
                current.copy(
                    confirmedRevision = maxOf(current.confirmedRevision, serverRevision),
                    pending = rebased,
                    terminalFailureCode = null,
                ),
            )
        }
    }

    override suspend fun acceptRemoteProgress(
        progress: ReaderProgress,
        snapshot: ReaderProgressSnapshotV4,
    ): Unit = io {
        val writable = database.writableDatabase
        writable.transaction {
            write(writable, progress)
            writeSyncState(
                writable,
                ReaderProgressDurableState(confirmedRevision = snapshot.revision),
            )
        }
    }

    override suspend fun recordTerminalFailure(mutationId: String, failureCode: String): Unit = io {
        val writable = database.writableDatabase
        writable.transaction {
            val current = readSyncState(writable)
            if (current.pending?.mutationId == mutationId) {
                writeSyncState(writable, current.copy(terminalFailureCode = failureCode))
            }
        }
    }

    override suspend fun delete(resourceId: String) {
        require(resourceId == identity.resourceId) { "Reader progress resource does not match its exact identity" }
        io {
            val writable = database.writableDatabase
            writable.transaction {
                writable.delete(PROGRESS_TABLE, "$PROGRESS_SOURCE_ID = ?", arrayOf(progressStorageKey()))
                writable.delete(SYNC_TABLE, "$SYNC_OWNER_KEY = ?", arrayOf(syncStorageKey()))
            }
        }
        legacyProgressStore?.delete(resourceId)
    }

    internal fun close() = database.close()

    private fun readByKey(database: SQLiteDatabase, key: String, resourceId: String): ReaderProgress? =
        database.query(
            PROGRESS_TABLE,
            arrayOf(PROGRESS_DOCUMENT),
            "$PROGRESS_SOURCE_ID = ?",
            arrayOf(key),
            null,
            null,
            null,
            "1",
        ).use { cursor ->
            if (!cursor.moveToFirst()) null else progressCodec.decode(cursor.getString(0)).also {
                require(it.resourceId == resourceId && matchesIdentity(it)) {
                    "Reader progress database identity mismatch"
                }
            }
        }

    private fun write(database: SQLiteDatabase, progress: ReaderProgress) {
        require(matchesIdentity(progress)) { "Reader progress does not match its exact identity" }
        val values = ContentValues().apply {
            put(PROGRESS_SOURCE_ID, progressStorageKey())
            put(PROGRESS_DOCUMENT, progressCodec.encode(progress))
        }
        database.insertWithOnConflict(PROGRESS_TABLE, null, values, SQLiteDatabase.CONFLICT_REPLACE)
            .also { rowId -> check(rowId != -1L) { "Reader progress save failed" } }
    }

    private fun readSyncState(database: SQLiteDatabase): ReaderProgressDurableState = database.query(
        SYNC_TABLE,
        arrayOf(SYNC_DOCUMENT),
        "$SYNC_OWNER_KEY = ?",
        arrayOf(syncStorageKey()),
        null,
        null,
        null,
        "1",
    ).use { cursor ->
        if (!cursor.moveToFirst()) ReaderProgressDurableState()
        else syncCodec.decode(cursor.getString(0))
    }

    private fun writeSyncState(database: SQLiteDatabase, state: ReaderProgressDurableState) {
        val values = ContentValues().apply {
            put(SYNC_OWNER_KEY, syncStorageKey())
            put(SYNC_DOCUMENT, syncCodec.encode(state))
        }
        database.insertWithOnConflict(SYNC_TABLE, null, values, SQLiteDatabase.CONFLICT_REPLACE)
            .also { rowId -> check(rowId != -1L) { "Reader sync state save failed" } }
    }

    // Exact reading position belongs to the account, not its current access token.
    private fun progressStorageKey(): String =
        "${readerAccountStorageKey(identity.namespace)}:${identity.stableKey}"

    // Pending writes remain isolated by authorization generation.
    private fun syncStorageKey(): String =
        "${readerAccountStorageKey(identity.namespace)}:${identity.namespace.authorizationVersion}:${identity.stableKey}"

    private fun migrateAuthorizationScopedProgress(database: SQLiteDatabase, resourceId: String): ReaderProgress? {
        val prefix = "${readerAccountStorageKey(identity.namespace)}:"
        val suffix = ":${identity.stableKey}"
        val candidates = mutableListOf<Pair<String, ReaderProgress>>()
        database.query(PROGRESS_TABLE, arrayOf(PROGRESS_SOURCE_ID, PROGRESS_DOCUMENT),
            "$PROGRESS_SOURCE_ID >= ? AND $PROGRESS_SOURCE_ID < ?", arrayOf(prefix, prefix + "\uffff"),
            null, null, null).use { cursor ->
            while (cursor.moveToNext()) {
                val key = cursor.getString(0)
                if (!key.startsWith(prefix) || !key.endsWith(suffix)) continue
                if (key.removePrefix(prefix).removeSuffix(suffix).toLongOrNull() == null) continue
                val progress = progressCodec.decode(cursor.getString(1))
                if (progress.resourceId == resourceId && matchesIdentity(progress)) candidates += key to progress
            }
        }
        val latest = candidates.maxByOrNull { it.second.updatedAtEpochMillis }?.second ?: return null
        database.transaction {
            write(database, latest)
            candidates.forEach { (key, _) -> delete(PROGRESS_TABLE, "$PROGRESS_SOURCE_ID = ?", arrayOf(key)) }
        }
        return latest
    }

    private fun matchesIdentity(progress: ReaderProgress): Boolean =
        progress.resourceId == identity.resourceId &&
            progress.deviceId == identity.clientId

    private suspend fun <T> io(block: () -> T): T = mutex.withLock {
        withContext(Dispatchers.IO) { block() }
    }

    private class ReaderDatabaseHelper(context: Context, databaseName: String) :
        SQLiteOpenHelper(context, databaseName, null, DATABASE_VERSION) {
        override fun onCreate(database: SQLiteDatabase) {
            database.execSQL(
                "CREATE TABLE $PROGRESS_TABLE (" +
                    "$PROGRESS_SOURCE_ID TEXT PRIMARY KEY NOT NULL," +
                    "$PROGRESS_DOCUMENT TEXT NOT NULL)",
            )
            database.execSQL(
                "CREATE TABLE $SYNC_TABLE (" +
                    "$SYNC_OWNER_KEY TEXT PRIMARY KEY NOT NULL," +
                    "$SYNC_DOCUMENT TEXT NOT NULL)",
            )
        }

        override fun onUpgrade(database: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            require(oldVersion in 1 until DATABASE_VERSION && newVersion == DATABASE_VERSION) {
                "Unsupported Reader progress database upgrade $oldVersion to $newVersion"
            }
            // Preserve opaque historical progress; never reinterpret missing identity fields.
            // Older schemas called this storage key source_id. Copy through the typed
            // ContentValues API so this also works on devices without RENAME COLUMN.
            val columns = database.query(PROGRESS_TABLE, null, null, null, null, null, null, "0")
                .use { it.columnNames.toSet() }
            if (PROGRESS_SOURCE_ID !in columns) {
                val oldTable = "reader_progress_previous"
                database.execSQL("ALTER TABLE $PROGRESS_TABLE RENAME TO $oldTable")
                database.execSQL("CREATE TABLE $PROGRESS_TABLE ($PROGRESS_SOURCE_ID TEXT PRIMARY KEY NOT NULL,$PROGRESS_DOCUMENT TEXT NOT NULL)")
                database.query(oldTable, arrayOf("source_id", PROGRESS_DOCUMENT), null, null, null, null, null)
                    .use { cursor ->
                        while (cursor.moveToNext()) {
                            database.insertOrThrow(PROGRESS_TABLE, null, ContentValues().apply {
                                put(PROGRESS_SOURCE_ID, cursor.getString(0))
                                put(PROGRESS_DOCUMENT, cursor.getString(1))
                            })
                        }
                    }
                database.execSQL("DROP TABLE $oldTable")
            }
            database.execSQL(
                "CREATE TABLE IF NOT EXISTS $SYNC_TABLE (" +
                    "$SYNC_OWNER_KEY TEXT PRIMARY KEY NOT NULL," +
                    "$SYNC_DOCUMENT TEXT NOT NULL)",
            )
        }
    }

    companion object {
        internal const val DATABASE_NAME = "reader-progress.db"
        internal const val DATABASE_VERSION = 7
        internal const val PROGRESS_TABLE = "reader_progress"
        internal const val PROGRESS_SOURCE_ID = "resource_id"
        internal const val PROGRESS_DOCUMENT = "document_json"
        internal const val OUTBOX_TABLE = "reader_progress_sync"
        internal const val SEQUENCE_TABLE = "reader_progress_sequence"
        internal const val SYNC_TABLE = "reader_progress_sync_v4"
        internal const val SYNC_OWNER_KEY = "owner_key"
        internal const val SYNC_DOCUMENT = "document_json"

        /** Deletes only rows written under the supplied ReaderSyncNamespace. */
        internal suspend fun clearNamespace(context: android.content.Context, namespace: com.ermao.library.shared.modules.reader.ReaderSyncNamespace) {
            val helper = ReaderDatabaseHelper(context.applicationContext, DATABASE_NAME)
            try {
                withContext(Dispatchers.IO) {
                    val prefix = "${readerAccountStorageKey(namespace)}:"
                    helper.writableDatabase.transaction {
                        deleteKeysWithPrefix(PROGRESS_TABLE, PROGRESS_SOURCE_ID, prefix)
                        deleteKeysWithPrefix(SYNC_TABLE, SYNC_OWNER_KEY, prefix)
                    }
                }
            } finally {
                helper.close()
            }
            AndroidReaderProgressStore.clearNamespace(context, namespace)
        }

        private fun SQLiteDatabase.deleteKeysWithPrefix(table: String, column: String, prefix: String) {
            val keys = query(table, arrayOf(column), null, null, null, null, null).use { cursor ->
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
