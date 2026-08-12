package com.ermao.library.features.reader

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressDatabase
import com.ermao.library.shared.modules.reader.ContentFingerprint
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressJson
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ReaderR4PersistenceInstrumentedTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val databaseName = "reader-progress-v4-test.db"

    @Before
    @After
    fun removeTestDatabase() {
        context.deleteDatabase(databaseName)
    }

    @Test
    fun exactProgressSurvivesAuthorizationVersionRotation() = runBlocking {
        val first = AndroidReaderProgressDatabase(
            context,
            identity(ReaderSyncNamespace("server", "user", 4)),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        first.save(progress(9_000))
        first.close()

        val rotated = AndroidReaderProgressDatabase(
            context,
            identity(ReaderSyncNamespace("server", "user", 5)),
            legacyProgressStore = null,
            databaseName = databaseName,
        )

        assertEquals(progress(9_000), rotated.load("volume-1"))
        rotated.close()
    }

    @Test
    fun v1DatabaseUpgradePreservesExactAndDropsRetiredSyncTables() = runBlocking {
        val namespace = ReaderSyncNamespace("server", "user", 4)
        createV1Database(namespace, progress(7_000))

        val upgraded = AndroidReaderProgressDatabase(
            context,
            identity(namespace.copy(authorizationVersion = 5)),
            legacyProgressStore = null,
            databaseName = databaseName,
        )

        assertEquals(progress(7_000), upgraded.load("volume-1"))
        upgraded.close()

        val readable = SQLiteDatabase.openDatabase(context.getDatabasePath(databaseName).path, null, SQLiteDatabase.OPEN_READONLY)
        readable.use { database ->
            assertFalse(tableExists(database, "reader_progress_sync"))
            assertFalse(tableExists(database, "reader_progress_sequence"))
        }
    }

    @Test
    fun exactRowsAreIsolatedByClientAndLocalFingerprint() = runBlocking {
        val namespace = ReaderSyncNamespace("server", "user", 1)
        val first = AndroidReaderProgressDatabase(
            context,
            identity(namespace),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        first.save(progress(1_000))
        first.close()

        val anotherClient = AndroidReaderProgressDatabase(
            context,
            identity(namespace).copy(clientId = "other-client"),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        assertEquals(null, anotherClient.load("volume-1"))
        anotherClient.close()

        val anotherContent = AndroidReaderProgressDatabase(
            context,
            identity(namespace).copy(localContentFingerprint = fingerprint('b')),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        assertEquals(null, anotherContent.load("volume-1"))
        anotherContent.close()

        val original = AndroidReaderProgressDatabase(
            context,
            identity(namespace),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        assertEquals(progress(1_000), original.load("volume-1"))
        original.close()
    }

    @Test
    fun earlyV4KeyMigratesOnlyAfterExactIdentityMatches() = runBlocking {
        val namespace = ReaderSyncNamespace("server", "user", 2)
        createEarlyV4Database(namespace, progress(5_000))

        val wrongClient = AndroidReaderProgressDatabase(
            context,
            identity(namespace).copy(clientId = "other-client"),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        assertEquals(null, wrongClient.load("volume-1"))
        wrongClient.close()

        val matching = AndroidReaderProgressDatabase(
            context,
            identity(namespace),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        assertEquals(progress(5_000), matching.load("volume-1"))
        matching.close()
    }

    private fun createV1Database(namespace: ReaderSyncNamespace, progress: ReaderProgress) {
        val database = SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(databaseName), null)
        database.use {
            it.execSQL("CREATE TABLE reader_progress (source_id TEXT PRIMARY KEY NOT NULL,document_json TEXT NOT NULL)")
            it.execSQL("CREATE TABLE reader_progress_sync (namespace_key TEXT PRIMARY KEY NOT NULL,document_json TEXT NOT NULL)")
            it.execSQL("CREATE TABLE reader_progress_sequence (server_user_key TEXT PRIMARY KEY NOT NULL,last_client_sequence INTEGER NOT NULL)")
            val values = ContentValues().apply {
                put("source_id", "${namespace.stableKey}|volume-1")
                put("document_json", ReaderProgressJson().encode(progress))
            }
            it.insertOrThrow("reader_progress", null, values)
            it.version = 1
        }
    }

    private fun createEarlyV4Database(namespace: ReaderSyncNamespace, progress: ReaderProgress) {
        val database = SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(databaseName), null)
        database.use {
            it.execSQL("CREATE TABLE reader_progress (source_id TEXT PRIMARY KEY NOT NULL,document_json TEXT NOT NULL)")
            val oldOwner = lengthPrefixed(namespace.serverIdentity, namespace.userId)
            val values = ContentValues().apply {
                put("source_id", lengthPrefixed(oldOwner, "volume-1"))
                put("document_json", ReaderProgressJson().encode(progress))
            }
            it.insertOrThrow("reader_progress", null, values)
            it.version = 2
        }
    }

    private fun tableExists(database: SQLiteDatabase, name: String): Boolean =
        database.query(
            "sqlite_master",
            arrayOf("name"),
            "type = ? AND name = ?",
            arrayOf("table", name),
            null,
            null,
            null,
        ).use { it.moveToFirst() }

    private fun progress(timestamp: Long) = ReaderProgress(
        "volume-1",
        ReflowReaderLocation(
            "chapter.xhtml",
            0.5,
            0.5,
            contentFingerprint = fingerprint(),
        ),
        timestamp,
        "android-client",
    )

    private fun identity(namespace: ReaderSyncNamespace) = ReaderLocalProgressIdentity(
        namespace,
        "android-client",
        "volume-1",
        fingerprint(),
    )

    private fun fingerprint(character: Char = 'a') = ContentFingerprint(
        "sha256:" + character.toString().repeat(64),
        "readium-kotlin:3.3.0",
        "v1",
    )
}

private fun lengthPrefixed(vararg values: String): String = buildString {
    values.forEach { value -> append(value.length).append(':').append(value) }
}
