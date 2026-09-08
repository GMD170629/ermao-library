package com.ermao.library.shared.modules.workmanagement.application

import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementError
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementErrorKind
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import kotlinx.coroutines.CancellationException

/** Invalidates cached reader positions after the server accepted a manual status. */
interface ReadingStatusResetPort {
    suspend fun resetBook(context: BookManagementContext, bookId: String)
    suspend fun resetResource(context: BookManagementContext, resourceId: String)
}

class ReadingStatusResettingRepository(
    private val delegate: WorkManagementRepository,
    private val resetPort: ReadingStatusResetPort,
) : WorkManagementRepository by delegate {
    override suspend fun setBookReadingStatus(context: BookManagementContext, bookId: String, status: ManagedReadingStatus): WorkManagementResult<Unit> =
        invalidateAfter(delegate.setBookReadingStatus(context, bookId, status)) { resetPort.resetBook(context, bookId) }

    override suspend fun setReadingStatus(context: BookManagementContext, resourceId: String, status: ManagedReadingStatus): WorkManagementResult<Unit> =
        invalidateAfter(delegate.setReadingStatus(context, resourceId, status)) { resetPort.resetResource(context, resourceId) }

    private suspend fun invalidateAfter(result: WorkManagementResult<Unit>, invalidate: suspend () -> Unit): WorkManagementResult<Unit> {
        if (result is WorkManagementResult.Failure) return result
        return try {
            invalidate()
            result
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (failure: Exception) {
            WorkManagementResult.Failure(WorkManagementError(WorkManagementErrorKind.Storage, "READING_STATUS_LOCAL_RESET_FAILED"))
        }
    }
}
