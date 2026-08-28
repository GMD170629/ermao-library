package com.ermao.library.features.reader

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressDatabase
import com.ermao.library.shared.modules.reader.EngineLocator
import com.ermao.library.shared.modules.reader.EngineLocatorPayload
import com.ermao.library.shared.modules.reader.AudioReaderLocation
import com.ermao.library.shared.modules.reader.ComicReaderLocation
import com.ermao.library.shared.modules.reader.PdfReaderLocation
import com.ermao.library.shared.modules.reader.ReaderEngine
import com.ermao.library.shared.modules.reader.ReaderEnginePlatform
import com.ermao.library.shared.modules.reader.ReaderProgress
import com.ermao.library.shared.modules.reader.ReaderProgressJson
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.createReaderProgressUpload
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
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
    fun versionSixProgressMigratesAcrossAuthorizationWithoutCopyingPendingWrites() = runBlocking {
        val namespace = ReaderSyncNamespace("server", "user", 4)
        val oldKey = "${lengthPrefixed(namespace.serverIdentity, namespace.userId)}:4:${identity(namespace).stableKey}"
        SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(databaseName), null).use { database ->
            database.execSQL("CREATE TABLE reader_progress (resource_id TEXT PRIMARY KEY NOT NULL,document_json TEXT NOT NULL)")
            database.execSQL("CREATE TABLE reader_progress_sync_v4 (owner_key TEXT PRIMARY KEY NOT NULL,document_json TEXT NOT NULL)")
            database.insertOrThrow("reader_progress", null, ContentValues().apply {
                put("resource_id", oldKey)
                put("document_json", ReaderProgressJson().encode(progress(8_000)))
            })
            database.version = 6
        }
        val migrated = AndroidReaderProgressDatabase(context, identity(namespace.copy(authorizationVersion = 5)),
            legacyProgressStore = null, databaseName = databaseName)
        assertEquals(progress(8_000), migrated.load("volume-1"))
        assertEquals(null, migrated.loadSyncState().pending)
        migrated.close()
        val reopened = AndroidReaderProgressDatabase(context, identity(namespace.copy(authorizationVersion = 6)),
            legacyProgressStore = null, databaseName = databaseName)
        assertEquals(progress(8_000), reopened.load("volume-1"))
        reopened.close()
    }

    @Test
    fun pendingSurvivesProcessReconstructionAndNewerMutationRebasesAfterConflict() = runBlocking {
        val namespace = ReaderSyncNamespace("server", "user", 4)
        val target = ReaderProgressSyncTarget(namespace, "work-1", "volume-1", ReaderFormat.Epub)
        val firstProgress = progress(1_000)
        val firstPending = createReaderProgressUpload(
            target,
            firstProgress,
            baseRevision = 0,
            mutationId = "58a3ac3c-52d0-41ed-9c85-0524b532f25b",
        ).mutation
        val first = AndroidReaderProgressDatabase(
            context,
            identity(namespace),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        first.commitProgressAndPending(firstProgress, firstPending)
        first.close()

        val reconstructed = AndroidReaderProgressDatabase(
            context,
            identity(namespace),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        assertEquals(firstPending.mutationId, reconstructed.loadSyncState().pending?.mutationId)

        val newerProgress = progress(2_000)
        val newerPending = createReaderProgressUpload(
            target,
            newerProgress,
            baseRevision = 0,
            mutationId = "3b5fa6ea-bb95-42ef-a1d4-6bcd65d47255",
        ).mutation
        reconstructed.commitProgressAndPending(newerProgress, newerPending)
        reconstructed.discardPendingAfterConflict(firstPending.mutationId, serverRevision = 5)

        val rebased = reconstructed.loadSyncState()
        assertEquals(5L, rebased.confirmedRevision)
        assertNotNull(rebased.pending)
        assertEquals(newerPending.mutationId, rebased.pending?.mutationId)
        assertEquals(5L, rebased.pending?.baseRevision)
        reconstructed.close()
    }

    @Test
    fun preUnionDatabaseUpgradePreservesOpaqueDocumentsWithoutInterpretingThem() = runBlocking {
        val namespace = ReaderSyncNamespace("server", "user", 4)
        createV1Database(namespace, progress(7_000))

        val upgraded = AndroidReaderProgressDatabase(
            context,
            identity(namespace.copy(authorizationVersion = 5)),
            legacyProgressStore = null,
            databaseName = databaseName,
        )

        assertEquals(null, upgraded.load("volume-1"))
        upgraded.close()

        val readable = SQLiteDatabase.openDatabase(context.getDatabasePath(databaseName).path, null, SQLiteDatabase.OPEN_READONLY)
        readable.use { database ->
            assertEquals(true, tableExists(database, "reader_progress_sync"))
            assertEquals(true, tableExists(database, "reader_progress_sequence"))
            database.query("reader_progress", arrayOf("document_json"), null, null, null, null, null).use {
                assertEquals(true, it.moveToFirst())
                assertEquals(ReaderProgressJson().encode(progress(7_000)), it.getString(0))
            }
        }
    }

    @Test
    fun exactRowsAreIsolatedByClientAndWorkVolumeIdentity() = runBlocking {
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

        val anotherWork = AndroidReaderProgressDatabase(
            context,
            identity(namespace).copy(bookId = "book-2"),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        assertEquals(null, anotherWork.load("volume-1"))
        anotherWork.close()

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
    fun publicationLocationMorphologiesRoundTripThroughSQLite() = runBlocking {
        val database = AndroidReaderProgressDatabase(
            context,
            identity(ReaderSyncNamespace("server", "user", 1)),
            legacyProgressStore = null,
            databaseName = databaseName,
        )
        val locations = listOf(
            progress(1_000).location,
            PdfReaderLocation(3, 0.375, engineLocator()),
            ComicReaderLocation("images/page-004.jpg", 3, engineLocator()),
            AudioReaderLocation("track-1", "chapter-2", 45_000, engineLocator()),
        )

        locations.forEachIndexed { index, location ->
            val expected = ReaderProgress("volume-1", location, index.toLong() + 2_000, "android-client", 25.0)
            database.save(expected)
            assertEquals(expected, database.load("volume-1"))
        }
        database.close()
    }

    @Test
    fun earlyV4KeyRemainsIsolatedAndNewExactProgressCanBeSaved() = runBlocking {
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
        assertEquals(null, matching.load("volume-1"))
        matching.save(progress(6_000))
        assertEquals(progress(6_000), matching.load("volume-1"))
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
            engineLocator = EngineLocator(
                engine = ReaderEngine.Readium,
                platform = ReaderEnginePlatform.Android,
                version = "readium-kotlin:3.3.0",
                payload = EngineLocatorPayload.parse(
                    """{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"body","progression":0.5,"totalProgression":0.5}}""",
                ),
            ),
        ),
        timestamp,
        "android-client",
    )

    private fun engineLocator() = EngineLocator(
        engine = ReaderEngine.Readium,
        platform = ReaderEnginePlatform.Android,
        version = "readium-kotlin:3.3.0",
        payload = EngineLocatorPayload.parse(
            """{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"body"}}""",
        ),
    )

    private fun identity(namespace: ReaderSyncNamespace) = ReaderLocalProgressIdentity(
        namespace,
        "android-client",
        "work-1",
        "volume-1",
    )

}

private fun lengthPrefixed(vararg values: String): String = buildString {
    values.forEach { value -> append(value.length).append(':').append(value) }
}
