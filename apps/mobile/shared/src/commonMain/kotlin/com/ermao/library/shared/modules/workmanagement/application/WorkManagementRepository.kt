package com.ermao.library.shared.modules.workmanagement.application

import com.ermao.library.shared.modules.workmanagement.domain.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.BookMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.BookMutationOutcome
import com.ermao.library.shared.modules.workmanagement.domain.BookDeletionOutcome
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult
import com.ermao.library.shared.modules.workmanagement.domain.ResourceMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult

interface WorkManagementRepository {
    suspend fun supportsNativeManagement(context: BookManagementContext): WorkManagementResult<Boolean>
    suspend fun updateBook(context: BookManagementContext, bookId: String, draft: BookMetadataDraft): WorkManagementResult<Unit>
    suspend fun uploadCover(
        context: BookManagementContext,
        bookId: String,
        sourceNodeId: String,
        title: String,
        description: String?,
        upload: CoverUpload,
    ): WorkManagementResult<Unit>
    suspend fun regenerateResourceCover(context: BookManagementContext, bookId: String, resourceId: String): WorkManagementResult<Unit>
    suspend fun regenerateBookCover(context: BookManagementContext, bookId: String, anchoredResourceId: String): WorkManagementResult<Unit>
    suspend fun rescanBook(context: BookManagementContext, sourceNodeId: String): WorkManagementResult<Unit>
    suspend fun deleteBook(context: BookManagementContext, bookId: String): WorkManagementResult<BookDeletionOutcome>
    suspend fun updateResource(context: BookManagementContext, bookId: String, resourceId: String, draft: ResourceMetadataDraft): WorkManagementResult<BookMutationOutcome>
    suspend fun loadMetadataProviders(context: BookManagementContext): WorkManagementResult<List<MetadataProvider>>
    suspend fun searchMetadata(context: BookManagementContext, bookId: String, sourceNodeId: String, providerId: String, query: String): WorkManagementResult<MetadataSearchResult>
    suspend fun applyMetadata(
        context: BookManagementContext,
        bookId: String,
        sourceNodeId: String,
        providerId: String,
        candidate: MetadataCandidate,
        fields: Set<MetadataField>,
        resourceId: String? = null,
        applyToAllResources: Boolean = false,
    ): WorkManagementResult<Unit>
    suspend fun loadKindleSettings(context: BookManagementContext): WorkManagementResult<KindleSettings>
    suspend fun sendToKindle(context: BookManagementContext, bookId: String, assetId: String): WorkManagementResult<KindleSendOutcome>
    suspend fun setReadingStatus(context: BookManagementContext, resourceId: String, status: ManagedReadingStatus): WorkManagementResult<Unit>
    suspend fun setBookReadingStatus(context: BookManagementContext, bookId: String, status: ManagedReadingStatus): WorkManagementResult<Unit>
}
