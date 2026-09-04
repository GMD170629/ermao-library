package com.ermao.library.features.reader.infrastructure

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionWriteResponse
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Verifies the Android v5 store on a device, including its latest-only outbox
 * transaction.  The test uses a private database name so it cannot mutate a
 * user's production rows; the production name/version are asserted below.
 */
@RunWith(AndroidJUnit4::class)
class ReaderV5PersistenceInstrumentedTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext
    private val databaseName = "reader-position-v5-instrumented-${UUID.randomUUID()}.db"
    private val namespace = ReaderSyncNamespace("instrumented-server", "instrumented-user", 1)
    private val identity = ReaderLocalProgressIdentity(
        namespace = namespace,
        clientId = "android-instrumented-client",
        bookId = "book-v5",
        resourceId = "resource-v5",
    )
    private lateinit var database: AndroidReaderV5Database

    @Before
    fun openV5Store() {
        database = AndroidReaderV5Database(context, identity, databaseName)
    }

    @After
    fun closeV5Store() {
        database.close()
        context.deleteDatabase(databaseName)
    }

    @Test
    fun productionNamespaceIsFreshV5AndOlderAckCannotClearNewPendingMutation() = runBlocking {
        assertEquals("reader-position-v5.db", AndroidReaderV5Database.DATABASE_NAME)
        assertEquals(1, AndroidReaderV5Database.DATABASE_VERSION)

        val first = local(1_000L)
        val firstMutation = first.toMutation("58a3ac3c-52d0-41ed-9c85-0524b532f25b")
        database.commitPositionAndPending(first, firstMutation)

        val latest = local(2_000L)
        val latestMutation = latest.toMutation("f4743f84-16dc-4202-ab50-729e4d036d16")
        database.commitPositionAndPending(latest, latestMutation)

        // Authorization generations are not part of the v5 storage key. A
        // process reopening the same account/client/book/resource must see
        // the latest pending body, while a different book remains isolated.
        database.close()
        database = AndroidReaderV5Database(
            context,
            identity.copy(namespace = namespace.copy(authorizationVersion = 2)),
            databaseName,
        )
        assertEquals(latest, database.loadPosition(identity.resourceId))
        assertEquals(latestMutation, database.loadPositionSyncState().pending)

        val otherBook = AndroidReaderV5Database(
            context,
            identity.copy(
                namespace = namespace.copy(authorizationVersion = 2),
                bookId = "another-book",
            ),
            databaseName,
        )
        try {
            assertEquals(null, otherBook.loadPositionSyncState().pending)
        } finally {
            otherBook.close()
        }

        val olderResponse = ReaderPositionWriteResponse(
            acceptedMutationId = firstMutation.mutationId,
            acceptedRevision = 1,
            currentSnapshot = snapshot(firstMutation.mutationId, revision = 1),
        )
        database.acknowledgePosition(olderResponse.acceptedMutationId, olderResponse)

        val afterOlderAck = database.loadPositionSyncState()
        assertEquals(
            "An in-flight response for the older body must not clear the latest pending body",
            latestMutation,
            afterOlderAck.pending,
        )
        assertNotNull(database.loadPosition(identity.resourceId))

        val latestResponse = olderResponse.copy(
            acceptedMutationId = latestMutation.mutationId,
            acceptedRevision = 2,
            currentSnapshot = snapshot(latestMutation.mutationId, revision = 2),
        )
        database.acknowledgePosition(latestResponse.acceptedMutationId, latestResponse)
        assertEquals(null, database.loadPositionSyncState().pending)
    }

    private fun local(capturedAt: Long) = ReaderPositionLocalState(
        resourceId = identity.resourceId,
        clientId = identity.clientId,
        capturedAtEpochMillis = capturedAt,
        position = ReaderPositionReportFixture.report(capturedAt.toDouble() / 10_000.0),
    )

    private fun snapshot(mutationId: String, revision: Long) = ReaderProgressSnapshotV5(
        resourceId = identity.resourceId,
        clientId = identity.clientId,
        revision = revision,
        mutationId = mutationId,
        capturedAtEpochMillis = revision * 1_000L,
        receivedAtEpochMillis = revision * 1_000L + 1L,
        position = ReaderPositionReportFixture.report(revision.toDouble() / 10.0),
    )
}

private object ReaderPositionReportFixture {
    fun report(progression: Double) = com.ermao.library.shared.modules.reader.ReaderPositionReport(
        locator = ReaderOpaqueLocator.parse(
            "{\"href\":\"chapter-$progression.xhtml\",\"locations\":{\"progression\":$progression}}",
        ),
        presentation = ReaderPositionPresentation(
            displayPercent = progression * 100.0,
            totalProgression = progression,
            currentHref = "chapter-$progression.xhtml",
            chapter = null,
            page = null,
            playback = null,
        ),
    )
}
