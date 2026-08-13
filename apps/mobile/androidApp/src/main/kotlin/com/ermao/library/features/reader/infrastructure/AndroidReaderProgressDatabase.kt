package com.ermao.library.features.reader.infrastructure

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.core.database.sqlite.transaction
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressConflict
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

/** Exact progress and the latest-only Reader v4 mutation/conflict in one SQLite database. */
internal class AndroidReaderProgressDatabase(
    context: Context,
    private val identity: ReaderLocalProgressIdentity,
    private val progressCodec: ReaderProgressJson = ReaderProgressJson(),
    private val syncCodec: ReaderProgressSyncStateJson = ReaderProgressSyncStateJson(),
    private val legacyProgressStore: ReaderProgressStore? = AndroidReaderProgressStore(context),
    databaseName: String = DATABASE_NAME,
) : ReaderProgressSyncStateStore {
    private val database = ReaderDatabaseHelper(context.applicationContext, databaseName)
    private val mutex = Mutex()

    override suspend fun load(sourceId: String): ReaderProgress? {
        require(sourceId == identity.volumeId) { "Reader progress source does not match its exact identity" }
        val stored = io { readByKey(database.readableDatabase, progressStorageKey(), sourceId) }
        if (stored != null) return stored

        // Upgrade old DB rows whose key included authorizationVersion. Multiple
        // old auth generations collapse to the newest exact local event.
        val migratedDatabaseProgress = io { migrateOldNamespacedRows(sourceId) }
        if (migratedDatabaseProgress != null) return migratedDatabaseProgress

        // R2 used one atomic JSON file per source. Import only after both v4 and
        // v3 DB misses, and delete the file only after the DB write commits.
        val migratedFileProgress = legacyProgressStore?.load(sourceId)
            ?.takeIf(::matchesIdentity)
            ?: return null
        save(migratedFileProgress)
        legacyProgressStore.delete(sourceId)
        return migratedFileProgress
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
        require(progress.sourceId == pending.sourceId)
        val writable = database.writableDatabase
        writable.transaction {
            write(writable, progress)
            val current = readSyncState(writable)
            writeSyncState(
                writable,
                current.copy(pending = pending, conflict = null, terminalFailureCode = null),
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
                    conflict = null,
                    terminalFailureCode = null,
                ),
            )
        }
    }

    override suspend fun recordConflict(conflict: ReaderProgressConflict): Unit = io {
        val writable = database.writableDatabase
        writable.transaction {
            val current = readSyncState(writable)
            if (current.pending?.mutationId == conflict.pending.mutationId) {
                writeSyncState(writable, current.copy(conflict = conflict, terminalFailureCode = null))
            }
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

    override suspend fun delete(sourceId: String) {
        require(sourceId == identity.volumeId) { "Reader progress source does not match its exact identity" }
        io {
            val writable = database.writableDatabase
            writable.transaction {
                writable.delete(PROGRESS_TABLE, "$PROGRESS_SOURCE_ID = ?", arrayOf(progressStorageKey()))
                oldRowKeys(writable, sourceId).forEach { oldKey ->
                    writable.delete(PROGRESS_TABLE, "$PROGRESS_SOURCE_ID = ?", arrayOf(oldKey))
                }
                writable.delete(SYNC_TABLE, "$SYNC_OWNER_KEY = ?", arrayOf(progressStorageKey()))
            }
        }
        legacyProgressStore?.delete(sourceId)
    }

    internal fun close() = database.close()

    private fun migrateOldNamespacedRows(sourceId: String): ReaderProgress? {
        val writable = database.writableDatabase
        return writable.transaction {
            val candidates = oldRows(writable, sourceId)
            val selected = candidates.maxWithOrNull(
                compareBy<Pair<String, ReaderProgress>> { it.second.updatedAtEpochMillis }
                    .thenBy { it.second.deviceId },
            )?.second
            if (selected != null) {
                write(writable, selected)
                candidates.forEach { (oldKey, _) ->
                    writable.delete(PROGRESS_TABLE, "$PROGRESS_SOURCE_ID = ?", arrayOf(oldKey))
                }
            }
            selected
        }
    }

    private fun oldRowKeys(database: SQLiteDatabase, sourceId: String): List<String> =
        oldRows(database, sourceId).map(Pair<String, ReaderProgress>::first)

    private fun oldRows(database: SQLiteDatabase, sourceId: String): List<Pair<String, ReaderProgress>> =
        database.query(
            PROGRESS_TABLE,
            arrayOf(PROGRESS_SOURCE_ID, PROGRESS_DOCUMENT),
            null,
            null,
            null,
            null,
            null,
        ).use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    val key = cursor.getString(0)
                    if (!isOldKeyForNamespace(key, sourceId)) continue
                    val progress = runCatching { progressCodec.decode(cursor.getString(1)) }.getOrNull()
                    if (progress?.sourceId == sourceId && matchesIdentity(progress)) add(key to progress)
                }
            }
        }

    private fun readByKey(database: SQLiteDatabase, key: String, sourceId: String): ReaderProgress? =
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
                require(it.sourceId == sourceId && matchesIdentity(it)) {
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
        arrayOf(progressStorageKey()),
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
            put(SYNC_OWNER_KEY, progressStorageKey())
            put(SYNC_DOCUMENT, syncCodec.encode(state))
        }
        database.insertWithOnConflict(SYNC_TABLE, null, values, SQLiteDatabase.CONFLICT_REPLACE)
            .also { rowId -> check(rowId != -1L) { "Reader sync state save failed" } }
    }

    private fun progressStorageKey(): String = identity.stableKey

    private fun matchesIdentity(progress: ReaderProgress): Boolean =
        progress.sourceId == identity.volumeId &&
            progress.deviceId == identity.clientId &&
            progress.location.contentFingerprint == identity.localContentFingerprint

    private fun isOldKeyForNamespace(key: String, sourceId: String): Boolean {
        val earlyV4Key = lengthPrefixed(
            lengthPrefixed(identity.namespace.serverIdentity, identity.namespace.userId),
            sourceId,
        )
        if (key == earlyV4Key) return true
        var cursor = 0
        fun segment(): String? {
            val colon = key.indexOf(':', cursor).takeIf { it >= cursor } ?: return null
            val length = key.substring(cursor, colon).toIntOrNull() ?: return null
            val start = colon + 1
            val end = start + length
            if (length < 0 || end > key.length) return null
            cursor = end
            return key.substring(start, end)
        }
        val serverIdentity = segment() ?: return false
        val userId = segment() ?: return false
        segment() ?: return false // old authorizationVersion
        return serverIdentity == identity.namespace.serverIdentity &&
            userId == identity.namespace.userId &&
            key.substring(cursor) == "|$sourceId"
    }

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
            // Exact progress is intentionally untouched. Only retired sync
            // machinery is removed; key/document migration is lazy and typed.
            database.execSQL("DROP TABLE IF EXISTS $OUTBOX_TABLE")
            database.execSQL("DROP TABLE IF EXISTS $SEQUENCE_TABLE")
            database.execSQL(
                "CREATE TABLE IF NOT EXISTS $SYNC_TABLE (" +
                    "$SYNC_OWNER_KEY TEXT PRIMARY KEY NOT NULL," +
                    "$SYNC_DOCUMENT TEXT NOT NULL)",
            )
        }
    }

    companion object {
        internal const val DATABASE_NAME = "reader-progress.db"
        internal const val DATABASE_VERSION = 3
        internal const val PROGRESS_TABLE = "reader_progress"
        internal const val PROGRESS_SOURCE_ID = "source_id"
        internal const val PROGRESS_DOCUMENT = "document_json"
        internal const val OUTBOX_TABLE = "reader_progress_sync"
        internal const val SEQUENCE_TABLE = "reader_progress_sequence"
        internal const val SYNC_TABLE = "reader_progress_sync_v4"
        internal const val SYNC_OWNER_KEY = "owner_key"
        internal const val SYNC_DOCUMENT = "document_json"
    }
}

private fun lengthPrefixed(vararg values: String): String = buildString {
    values.forEach { value ->
        append(value.length)
        append(':')
        append(value)
    }
}
