package com.ermao.library.features.reader.infrastructure

import com.ermao.library.features.reader.application.ReaderBookmarkChange
import com.ermao.library.shared.modules.reader.ReaderBookmark
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncPort
import com.ermao.library.shared.modules.reader.ReaderBookmarkSyncTarget
import com.ermao.library.shared.modules.reader.ReaderPositionReport
import com.ermao.library.shared.modules.reader.ReaderPositionReportJson
import com.ermao.library.shared.modules.reader.domain.mergeReaderBookmarks
import java.time.Instant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * The single Android owner for Reader v5 bookmark state and synchronization.
 *
 * A session supplies only format-specific position creation, identity and
 * navigation callbacks. The stored shape remains the existing opaque v5
 * position report, so EPUB, comic and PDF share one persistence contract.
 */
internal class AndroidReaderBookmarkCoordinator(
    private val bookmarkStore: AndroidReaderBookmarkStore?,
    private val bookmarkSyncPort: ReaderBookmarkSyncPort?,
    private val bookmarkSyncTarget: ReaderBookmarkSyncTarget?,
    private val currentPosition: () -> ReaderPositionReport?,
    private val bookmarkLabel: () -> String,
    private val bookmarkId: (ReaderPositionReport) -> String,
    private val navigateToPosition: (ReaderPositionReport) -> Boolean,
    private val nowEpochMillis: () -> Long = System::currentTimeMillis,
) {
    private val positionJson = ReaderPositionReportJson()
    private val bookmarkSyncMutex = Mutex()
    private val _bookmarks = MutableStateFlow<List<ReaderBookmark>>(emptyList())
    private val _bookmarkSyncPending = MutableStateFlow(false)

    private var bookmarkRecords: List<AndroidReaderBookmarkRecord> = emptyList()
    private var removedBookmark: AndroidReaderBookmarkRecord? = null
    private var bookmarkScope: CoroutineScope? = null
    private var syncJob: Job? = null

    val bookmarks: StateFlow<List<ReaderBookmark>> = _bookmarks.asStateFlow()
    val bookmarkSyncPending: StateFlow<Boolean> = _bookmarkSyncPending.asStateFlow()

    /** Loads the durable local snapshot before the navigator is shown. */
    fun load() {
        val state = runCatching { bookmarkStore?.load() }.getOrNull() ?: return
        bookmarkRecords = state.bookmarks
        _bookmarks.value = state.bookmarks.mapNotNull(AndroidReaderBookmarkRecord::shared)
        _bookmarkSyncPending.value = state.pending != null
    }

    /** Starts the existing refresh/outbox lifecycle on the session scope. */
    fun bind(scope: CoroutineScope) {
        bookmarkScope = scope
        if (bookmarkStore == null || bookmarkSyncPort == null || bookmarkSyncTarget == null) return
        syncJob?.cancel()
        syncJob = scope.launch {
            launch { refreshBookmarksFromServer() }
            launch { flushBookmarkOutbox() }
        }
    }

    fun release() {
        syncJob?.cancel()
        syncJob = null
        bookmarkScope = null
    }

    fun toggleCurrentBookmark(): ReaderBookmarkChange? {
        if (bookmarkStore == null) return null
        val position = currentPosition() ?: return null
        val id = bookmarkId(position).takeIf(String::isNotBlank) ?: return null
        val existing = bookmarkRecords.firstOrNull { it.id == id }
        val added = existing == null
        val next = if (existing != null) {
            removedBookmark = existing
            bookmarkRecords.filterNot { it.id == id }
        } else {
            bookmarkRecords + AndroidReaderBookmarkRecord(
                id = id,
                positionJson = positionJson.encode(position),
                label = bookmarkLabel().take(MAXIMUM_BOOKMARK_LABEL_LENGTH),
                createdAt = Instant.ofEpochMilli(nowEpochMillis()).toString(),
            )
        }
        commitBookmarkMutation(next)
        return ReaderBookmarkChange(id, added)
    }

    fun undoBookmarkChange(change: ReaderBookmarkChange): Boolean =
        if (change.added) {
            if (bookmarkRecords.none { it.id == change.bookmarkId }) {
                false
            } else {
                commitBookmarkMutation(bookmarkRecords.filterNot { it.id == change.bookmarkId })
                true
            }
        } else {
            undoBookmarkRemoval(change.bookmarkId)
        }

    fun removeBookmark(id: String) {
        removedBookmark = bookmarkRecords.firstOrNull { it.id == id } ?: return
        commitBookmarkMutation(bookmarkRecords.filterNot { it.id == id })
    }

    fun undoBookmarkRemoval(id: String): Boolean {
        val bookmark = removedBookmark?.takeIf { it.id == id } ?: return false
        if (bookmarkRecords.any { it.id == id }) return false
        removedBookmark = null
        commitBookmarkMutation(bookmarkRecords + bookmark)
        return true
    }

    fun goToBookmark(id: String): Boolean {
        val record = bookmarkRecords.firstOrNull { it.id == id } ?: return false
        val position = runCatching { positionJson.decode(record.positionJson) }.getOrNull() ?: return false
        return navigateToPosition(position)
    }

    private fun commitBookmarkMutation(next: List<AndroidReaderBookmarkRecord>) {
        val store = bookmarkStore ?: return
        val ordered = next.sortedWith(compareBy<AndroidReaderBookmarkRecord>({
            runCatching { positionJson.decode(it.positionJson).presentation.displayPercent }
                .getOrDefault(0.0)
        }, { it.createdAt }, { it.id }))
        val hasSyncTarget = bookmarkSyncPort != null && bookmarkSyncTarget != null
        store.save(
            AndroidReaderBookmarkState(
                bookmarks = ordered,
                pending = ordered.takeIf { hasSyncTarget },
            ),
        )
        bookmarkRecords = ordered
        _bookmarks.value = ordered.mapNotNull(AndroidReaderBookmarkRecord::shared)
        _bookmarkSyncPending.value = hasSyncTarget
        if (hasSyncTarget) bookmarkScope?.launch { flushBookmarkOutbox() }
    }

    private suspend fun refreshBookmarksFromServer() {
        val store = bookmarkStore ?: return
        val port = bookmarkSyncPort ?: return
        val target = bookmarkSyncTarget ?: return
        val response = port.load(target)
        if (!response.succeeded) return
        val state = store.load()
        val merged = mergeReaderBookmarks(
            local = state.bookmarks.mapNotNull(AndroidReaderBookmarkRecord::shared),
            remote = response.bookmarks,
            hasPendingLocalSnapshot = state.pending != null,
        )
        if (state.pending != null) return
        val localById = state.bookmarks.associateBy(AndroidReaderBookmarkRecord::id)
        val records = merged.map { bookmark ->
            localById[bookmark.id] ?: bookmark.record()
        }
        store.save(AndroidReaderBookmarkState(records, null))
        bookmarkRecords = records
        _bookmarks.value = merged
        _bookmarkSyncPending.value = false
    }

    private suspend fun flushBookmarkOutbox() = bookmarkSyncMutex.withLock {
        val store = bookmarkStore ?: return@withLock
        val port = bookmarkSyncPort ?: return@withLock
        val target = bookmarkSyncTarget ?: return@withLock
        while (true) {
            val before = store.load()
            val pending = before.pending ?: break
            val response = port.replace(target, pending.mapNotNull(AndroidReaderBookmarkRecord::shared))
            if (!response.succeeded) break
            val latest = store.load()
            if (latest.pending != pending) continue
            val localById = latest.bookmarks.associateBy(AndroidReaderBookmarkRecord::id)
            val acknowledged = response.bookmarks.map { localById[it.id] ?: it.record() }
            store.save(AndroidReaderBookmarkState(acknowledged, null))
            bookmarkRecords = acknowledged
            _bookmarks.value = response.bookmarks
            _bookmarkSyncPending.value = false
            break
        }
    }

    private companion object {
        const val MAXIMUM_BOOKMARK_LABEL_LENGTH = 500
    }
}

private val bookmarkPositionJson = ReaderPositionReportJson()

private fun AndroidReaderBookmarkRecord.shared(): ReaderBookmark? = runCatching {
    ReaderBookmark(
        id = id,
        position = bookmarkPositionJson.decode(positionJson),
        label = label,
        createdAt = createdAt,
    )
}.getOrNull()

private fun ReaderBookmark.record(): AndroidReaderBookmarkRecord = AndroidReaderBookmarkRecord(
    id = id,
    positionJson = bookmarkPositionJson.encode(position),
    label = label,
    createdAt = createdAt,
)
