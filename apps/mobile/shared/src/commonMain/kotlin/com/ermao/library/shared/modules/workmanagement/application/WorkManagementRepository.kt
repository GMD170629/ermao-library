package com.ermao.library.shared.modules.workmanagement.application

import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.BookMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.BookDeletionOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.CoverMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult
import com.ermao.library.shared.modules.workmanagement.domain.ResourceMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import com.ermao.library.shared.modules.workmanagement.domain.ManagementTarget
import com.ermao.library.shared.modules.workmanagement.domain.ManagementSnapshot
import com.ermao.library.shared.modules.workmanagement.domain.ManagementFieldValue
import com.ermao.library.shared.modules.workmanagement.domain.RecognizedField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataApplyOutcome

interface WorkManagementRepository {
    suspend fun loadBookCompleted(context: BookManagementContext, bookId: String): WorkManagementResult<Boolean>

    suspend fun saveBookFields(context: BookManagementContext, bookId: String, draft: BookMetadataDraft): WorkManagementResult<Unit>
    suspend fun replaceBookTags(context: BookManagementContext, bookId: String, current: List<String>, next: List<String>): WorkManagementResult<Unit>
    suspend fun loadManagementSnapshot(context: BookManagementContext, target: ManagementTarget): WorkManagementResult<ManagementSnapshot>
    suspend fun saveResourceFields(context: BookManagementContext, bookId: String, resourceId: String, fields: List<ManagementFieldValue>): WorkManagementResult<Unit>
    suspend fun saveSourcePresentation(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String, removeCover: Boolean, upload: CoverUpload?): WorkManagementResult<Unit>
    suspend fun regenerateBookImage(context: BookManagementContext, bookId: String): WorkManagementResult<Unit>
    suspend fun deleteResourceSource(context: BookManagementContext, bookId: String, resourceId: String, confirmation: String, idempotencyKey: String): WorkManagementResult<Unit>
    suspend fun applyRecognizedFields(context: BookManagementContext, target: ManagementTarget, candidate: MetadataCandidate, fields: List<RecognizedField>): WorkManagementResult<MetadataApplyOutcome>
    suspend fun applyDirectoryMetadata(context: BookManagementContext, bookId: String, sourceNodeId: String, title: String, description: String): WorkManagementResult<Unit>

    suspend fun uploadCover(
        context: BookManagementContext,
        bookId: String,
        resourceId: String,
        upload: CoverUpload,
    ): WorkManagementResult<CoverMutationOutcome>
    suspend fun regenerateResourceCover(context: BookManagementContext, bookId: String, resourceId: String): WorkManagementResult<Unit>

    suspend fun rescanBook(context: BookManagementContext, sourceNodeId: String): WorkManagementResult<Unit>
    suspend fun deleteBook(context: BookManagementContext, bookId: String): WorkManagementResult<BookDeletionOutcome>

    suspend fun loadMetadataProviders(context: BookManagementContext): WorkManagementResult<List<MetadataProvider>>
    suspend fun searchMetadata(context: BookManagementContext, bookId: String, sourceNodeId: String, providerId: String, query: String): WorkManagementResult<MetadataSearchResult>

    suspend fun loadKindleSettings(context: BookManagementContext): WorkManagementResult<KindleSettings>
    suspend fun sendToKindle(context: BookManagementContext, bookId: String, assetId: String): WorkManagementResult<KindleSendOutcome>
    suspend fun setReadingStatus(context: BookManagementContext, resourceId: String, status: ManagedReadingStatus): WorkManagementResult<Unit>
    suspend fun setBookReadingStatus(context: BookManagementContext, bookId: String, status: ManagedReadingStatus): WorkManagementResult<Unit>
}
