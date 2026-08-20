package com.ermao.library.shared.modules.workmanagement.application

import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import com.ermao.library.shared.modules.workmanagement.domain.KindleSendOutcome
import com.ermao.library.shared.modules.workmanagement.domain.KindleSettings
import com.ermao.library.shared.modules.workmanagement.domain.ManagedMediaKind
import com.ermao.library.shared.modules.workmanagement.domain.ManagedReadingStatus
import com.ermao.library.shared.modules.workmanagement.domain.MetadataCandidate
import com.ermao.library.shared.modules.workmanagement.domain.MetadataField
import com.ermao.library.shared.modules.workmanagement.domain.MetadataProvider
import com.ermao.library.shared.modules.workmanagement.domain.MetadataSearchResult
import com.ermao.library.shared.modules.workmanagement.domain.VolumeMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementContext
import com.ermao.library.shared.modules.workmanagement.domain.WorkManagementResult
import com.ermao.library.shared.modules.workmanagement.domain.WorkMetadataDraft
import com.ermao.library.shared.modules.workmanagement.domain.WorkMutationOutcome

interface WorkManagementRepository {
    suspend fun supportsNativeManagement(context: WorkManagementContext): WorkManagementResult<Boolean>
    suspend fun updateWork(context: WorkManagementContext, workId: String, draft: WorkMetadataDraft): WorkManagementResult<Unit>
    suspend fun uploadCover(context: WorkManagementContext, workId: String, upload: CoverUpload): WorkManagementResult<Unit>
    suspend fun regenerateCover(context: WorkManagementContext, workId: String): WorkManagementResult<Unit>
    suspend fun updateVolume(context: WorkManagementContext, workId: String, volumeId: String, draft: VolumeMetadataDraft): WorkManagementResult<WorkMutationOutcome>
    suspend fun reclassifyVolume(context: WorkManagementContext, workId: String, volumeId: String, mediaKind: ManagedMediaKind): WorkManagementResult<WorkMutationOutcome>
    suspend fun loadMetadataProviders(context: WorkManagementContext, mediaKind: ManagedMediaKind): WorkManagementResult<List<MetadataProvider>>
    suspend fun searchMetadata(context: WorkManagementContext, workId: String, providerId: String, query: String): WorkManagementResult<MetadataSearchResult>
    suspend fun applyMetadata(
        context: WorkManagementContext,
        workId: String,
        providerId: String,
        candidate: MetadataCandidate,
        fields: Set<MetadataField>,
        volumeId: String?,
        applyToAllVolumes: Boolean,
    ): WorkManagementResult<Unit>
    suspend fun loadKindleSettings(context: WorkManagementContext): WorkManagementResult<KindleSettings>
    suspend fun sendToKindle(context: WorkManagementContext, workId: String, fileId: String): WorkManagementResult<KindleSendOutcome>
    suspend fun setReadingStatus(context: WorkManagementContext, volumeId: String, status: ManagedReadingStatus): WorkManagementResult<Unit>
}
