package com.ermao.library.shared.modules.workmanagement.application

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
    private val values = MutableStateFlow<Map<String, Boolean?>>(emptyMap())
    val state = values.asStateFlow()
    private val lock = Mutex()
    private val permits = Semaphore(4)
    private val pending = mutableMapOf<String, CompletableDeferred<Boolean?>>()

    suspend fun prepare(bookId: String): Boolean? {
        var ownsRequest = false
        val request = lock.withLock {
            if (values.value.containsKey(bookId)) return values.value[bookId]
            pending[bookId] ?: CompletableDeferred<Boolean?>().also { pending[bookId] = it; ownsRequest = true }
        }
        if (!ownsRequest) return request.await()
        var completed: Boolean? = null
        try {
            completed = permits.withPermit {
                when (val result = repository.loadBookCompleted(context, bookId)) {
                    is WorkManagementResult.Content -> result.value
                    is WorkManagementResult.Failure -> null
                }
            }
            if (pending[bookId] === request && completed != null) put(bookId, completed)
            return completed
        } finally {
            request.complete(completed)
            // All entry points are owned by the platform's main presentation scope.
            if (pending[bookId] === request) pending.remove(bookId)
        }
    }

    fun put(bookId: String, completed: Boolean?) {
        values.update { previous ->
            val next = (previous - bookId) + (bookId to completed)
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
