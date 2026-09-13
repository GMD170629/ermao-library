package com.ermao.library.shared.modules.workmanagement.application

import com.ermao.library.shared.modules.workmanagement.domain.ManagementMenuContext
import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit

/** Session-owned, bounded cache for list endpoints that omit the explicit completed flag. */
internal class BookMenuStateCache(
    private val repository: WorkManagementRepository,
    private val context: BookManagementContext,
) {
    private val values = MutableStateFlow<Map<String, ManagementMenuContext?>>(emptyMap())
    val state = values.asStateFlow()
    private val lock = Mutex()
    private val permits = Semaphore(4)
    private val pending = mutableMapOf<String, CompletableDeferred<ManagementMenuContext?>>()

    suspend fun prepare(bookId: String): ManagementMenuContext? {
        var ownsRequest = false
        val request = lock.withLock {
            if (values.value.containsKey(bookId)) return values.value[bookId]
            pending[bookId] ?: CompletableDeferred<ManagementMenuContext?>().also { pending[bookId] = it; ownsRequest = true }
        }
        if (!ownsRequest) return request.await()
        var completed: ManagementMenuContext? = null
        try {
            completed = permits.withPermit {
                when (val result = repository.loadBookMenuContext(context, bookId)) {
                    is WorkManagementResult.Content -> result.value
                    is WorkManagementResult.Failure -> null
                }
            }
            if (pending[bookId] === request && completed != null) put(bookId, completed.completed, completed.kindleSendAvailable)
            return completed
        } finally {
            request.complete(completed)
            // All entry points are owned by the platform's main presentation scope.
            if (pending[bookId] === request) pending.remove(bookId)
        }
    }

    fun put(bookId: String, completed: Boolean?, kindleSendAvailable: Boolean = values.value[bookId]?.kindleSendAvailable == true) {
        values.update { previous ->
            val next = (previous - bookId) + (bookId to ManagementMenuContext(completed = completed, kindleSendAvailable = kindleSendAvailable))
            if (next.size > 256) next - next.keys.first() else next
        }
    }

    fun invalidate(bookId: String) {
        pending.remove(bookId)
        values.update { it - bookId }
    }

    fun clear() {
        pending.clear()
        values.value = emptyMap()
    }
}
