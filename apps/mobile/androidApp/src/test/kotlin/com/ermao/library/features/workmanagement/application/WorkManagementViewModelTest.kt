package com.ermao.library.features.workmanagement.application

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import com.ermao.library.shared.modules.workmanagement.application.WorkManagementRepository
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
import kotlin.test.assertEquals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class WorkManagementViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun reclassifyReportsCompletionWithoutChangingDirectoryOwnership() = runTest(dispatcher) {
        val repository = FakeWorkManagementRepository()
        val viewModel = WorkManagementViewModel(
            repository = repository,
            context = context,
            workId = WORK_ID,
            onUnauthorized = {},
        )
        advanceUntilIdle()

        viewModel.reclassifyVolume(VOLUME_ID, ManagedMediaKind.Comic)
        advanceUntilIdle()

        assertEquals(Triple(WORK_ID, VOLUME_ID, ManagedMediaKind.Comic), repository.reclassified)
        assertEquals(WorkManagementCompletion.VolumeReclassified, viewModel.uiState.value.completedMutation)
    }

    private class FakeWorkManagementRepository : WorkManagementRepository {
        var reclassified: Triple<String, String, ManagedMediaKind>? = null

        override suspend fun supportsNativeManagement(context: WorkManagementContext) =
            WorkManagementResult.Content(true)

        override suspend fun reclassifyVolume(
            context: WorkManagementContext,
            workId: String,
            volumeId: String,
            mediaKind: ManagedMediaKind,
        ): WorkManagementResult<WorkMutationOutcome> {
            reclassified = Triple(workId, volumeId, mediaKind)
            return WorkManagementResult.Content(WorkMutationOutcome(workId, "operation"))
        }

        override suspend fun updateWork(
            context: WorkManagementContext,
            workId: String,
            draft: WorkMetadataDraft,
        ) = unused()

        override suspend fun uploadCover(
            context: WorkManagementContext,
            workId: String,
            upload: CoverUpload,
        ) = unused()

        override suspend fun regenerateCover(context: WorkManagementContext, workId: String) = unused()

        override suspend fun updateVolume(
            context: WorkManagementContext,
            workId: String,
            volumeId: String,
            draft: VolumeMetadataDraft,
        ) = unused()

        override suspend fun loadMetadataProviders(
            context: WorkManagementContext,
            mediaKind: ManagedMediaKind,
        ): WorkManagementResult<List<MetadataProvider>> = unused()

        override suspend fun searchMetadata(
            context: WorkManagementContext,
            workId: String,
            providerId: String,
            query: String,
        ): WorkManagementResult<MetadataSearchResult> = unused()

        override suspend fun applyMetadata(
            context: WorkManagementContext,
            workId: String,
            providerId: String,
            candidate: MetadataCandidate,
            fields: Set<MetadataField>,
            volumeId: String?,
            applyToAllVolumes: Boolean,
        ) = unused()

        override suspend fun loadKindleSettings(
            context: WorkManagementContext,
        ): WorkManagementResult<KindleSettings> = unused()

        override suspend fun sendToKindle(
            context: WorkManagementContext,
            workId: String,
            fileId: String,
        ): WorkManagementResult<KindleSendOutcome> = unused()

        override suspend fun setReadingStatus(
            context: WorkManagementContext,
            volumeId: String,
            status: ManagedReadingStatus,
        ) = unused()

        private fun unused(): Nothing = error("unused")
    }

    private companion object {
        const val WORK_ID = "work"
        const val VOLUME_ID = "volume"
        val context = WorkManagementContext(
            profile = ServerProfile(
                id = "profile",
                displayName = "Library",
                baseUrl = (ServerBaseUrl.parse("https://library.example") as ServerBaseUrlParseResult.Valid).baseUrl,
                serverIdentity = "server",
                isActive = true,
                tlsMode = TlsMode.SystemTrust,
            ),
            namespace = PrivateDataNamespace("server", "user", 1),
        )
    }
}
