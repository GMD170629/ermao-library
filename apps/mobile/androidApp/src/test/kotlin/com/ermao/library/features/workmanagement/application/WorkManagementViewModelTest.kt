package com.ermao.library.features.workmanagement.application

import com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace
import com.ermao.library.shared.modules.downloads.CompletedDownloadArtifact
import com.ermao.library.shared.modules.downloads.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.DownloadIdentity
import com.ermao.library.shared.modules.downloads.DownloadNamespace
import com.ermao.library.shared.modules.downloads.DownloadReaderType
import com.ermao.library.shared.modules.downloads.DownloadSource
import com.ermao.library.shared.modules.downloads.DownloadsRuntime
import com.ermao.library.shared.modules.downloads.InMemoryDownloadCatalogRepository
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
import com.ermao.library.shared.modules.workmanagement.domain.WorkTransferTarget
import kotlin.test.assertEquals
import kotlin.test.assertNull
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
    fun splitMovesCompletedDownloadToServerTargetWorkAndVersion() = runTest(dispatcher) {
        val catalog = InMemoryDownloadCatalogRepository()
        val runtime = DownloadsRuntime(catalog)
        catalog.saveArtifact(artifact(volumeId = "volume-keep"))
        catalog.saveArtifact(artifact(volumeId = "volume-split"))
        val viewModel = viewModel(
            runtime,
            FakeWorkManagementRepository(
                splitOutcome = WorkMutationOutcome(
                    workId = SOURCE_WORK_ID,
                    targetWorkId = "work-target",
                    targetVersionId = "version-target",
                ),
            ),
        )
        advanceUntilIdle()

        viewModel.splitVolume("volume-split", "Split Work", "New Author")
        advanceUntilIdle()

        val moved = requireNotNull(runtime.artifact(namespace, "volume-split"))
        assertEquals("work-target", moved.identity.workId)
        assertEquals("version-target", moved.descriptor.versionId)
        assertEquals(STRUCTURAL_MOVE_VERSION_SOURCE_KEY, moved.descriptor.versionSourceKey)
        assertNull(moved.descriptor.versionSourceName)
        assertNull(moved.descriptor.versionCompleted)
        assertEquals("local://volume-split", moved.localReference)
        assertEquals(10, moved.verifiedBytes)

        val kept = requireNotNull(runtime.artifact(namespace, "volume-keep"))
        assertEquals(SOURCE_WORK_ID, kept.identity.workId)
        assertEquals(SOURCE_VERSION_ID, kept.descriptor.versionId)

        val works = runtime.downloadedWorks(namespace)
        assertEquals(setOf(SOURCE_WORK_ID, "work-target"), works.map { it.workId }.toSet())
        val target = works.single { it.workId == "work-target" }
        assertEquals(listOf("version-target"), target.versions.map { it.versionId })
        assertEquals(listOf("volume-split"), target.versions.single().artifacts.map { it.identity.volumeId })
        assertEquals(WorkManagementCompletion.VolumeSplit, viewModel.uiState.value.completedMutation)
    }

    @Test
    fun transferMovesCompletedDownloadToServerTargetWorkAndVersion() = runTest(dispatcher) {
        val catalog = InMemoryDownloadCatalogRepository()
        val runtime = DownloadsRuntime(catalog)
        catalog.saveArtifact(artifact())
        val viewModel = viewModel(
            runtime,
            FakeWorkManagementRepository(
                transferOutcome = WorkMutationOutcome(
                    workId = SOURCE_WORK_ID,
                    targetWorkId = "work-target",
                    targetVersionId = "version-target",
                ),
            ),
        )
        advanceUntilIdle()

        viewModel.transferVolume(
            "volume",
            WorkTransferTarget("work-target", "Target Work", "Target Author"),
        )
        advanceUntilIdle()

        val moved = requireNotNull(runtime.artifact(namespace, "volume"))
        assertEquals("work-target", moved.identity.workId)
        assertEquals("version-target", moved.descriptor.versionId)
        assertEquals(STRUCTURAL_MOVE_VERSION_SOURCE_KEY, moved.descriptor.versionSourceKey)
        assertNull(moved.descriptor.versionSourceName)
        assertNull(moved.descriptor.versionCompleted)
        assertEquals("local://volume", moved.localReference)
        assertEquals(10, moved.verifiedBytes)
        val grouped = runtime.downloadedWorks(namespace).single()
        assertEquals("work-target", grouped.workId)
        assertEquals(listOf("version-target"), grouped.versions.map { it.versionId })
    }

    @Test
    fun reclassifyLeavesDownloadVersionOwnershipUnchanged() = runTest(dispatcher) {
        val catalog = InMemoryDownloadCatalogRepository()
        val runtime = DownloadsRuntime(catalog)
        val original = artifact()
        catalog.saveArtifact(original)
        val viewModel = viewModel(
            runtime,
            FakeWorkManagementRepository(
                reclassifyOutcome = WorkMutationOutcome(
                    workId = SOURCE_WORK_ID,
                    targetWorkId = SOURCE_WORK_ID,
                    targetVersionId = "ignored-version",
                ),
            ),
        )
        advanceUntilIdle()

        viewModel.reclassifyVolume("volume", ManagedMediaKind.Comic)
        advanceUntilIdle()

        val current = requireNotNull(runtime.artifact(namespace, "volume"))
        assertEquals(original.identity.workId, current.identity.workId)
        assertEquals(original.descriptor.versionId, current.descriptor.versionId)
        assertEquals(original.descriptor.versionSourceKey, current.descriptor.versionSourceKey)
        assertEquals(original.descriptor.versionSourceName, current.descriptor.versionSourceName)
        assertEquals(original.localReference, current.localReference)
        assertEquals(original.verifiedBytes, current.verifiedBytes)
        assertEquals(WorkManagementCompletion.VolumeReclassified, viewModel.uiState.value.completedMutation)
    }

    @Test
    fun missingTargetVersionIdLeavesLocalDownloadUnchanged() = runTest(dispatcher) {
        val catalog = InMemoryDownloadCatalogRepository()
        val runtime = DownloadsRuntime(catalog)
        val original = artifact()
        catalog.saveArtifact(original)
        val viewModel = viewModel(
            runtime,
            FakeWorkManagementRepository(
                splitOutcome = WorkMutationOutcome(
                    workId = SOURCE_WORK_ID,
                    targetWorkId = "work-target",
                    targetVersionId = null,
                ),
            ),
        )
        advanceUntilIdle()

        viewModel.splitVolume("volume", "Split Work", null)
        advanceUntilIdle()

        assertEquals(original, runtime.artifact(namespace, "volume"))
        assertEquals(WorkManagementCompletion.VolumeSplit, viewModel.uiState.value.completedMutation)
    }

    @Test
    fun missingTargetWorkIdLeavesLocalDownloadUnchangedEvenWhenTransferTargetIsKnown() = runTest(dispatcher) {
        val catalog = InMemoryDownloadCatalogRepository()
        val runtime = DownloadsRuntime(catalog)
        val original = artifact()
        catalog.saveArtifact(original)
        val viewModel = viewModel(
            runtime,
            FakeWorkManagementRepository(
                transferOutcome = WorkMutationOutcome(
                    workId = SOURCE_WORK_ID,
                    targetWorkId = null,
                    targetVersionId = "version-target",
                ),
            ),
        )
        advanceUntilIdle()

        viewModel.transferVolume(
            "volume",
            WorkTransferTarget("work-target", "Target Work", "Target Author"),
        )
        advanceUntilIdle()

        assertEquals(original, runtime.artifact(namespace, "volume"))
    }

    private fun viewModel(
        runtime: DownloadsRuntime,
        repository: WorkManagementRepository,
    ) = WorkManagementViewModel(
        repository = repository,
        context = context,
        workId = SOURCE_WORK_ID,
        downloadsRuntime = runtime,
        downloadNamespace = namespace,
        onUnauthorized = {},
    )

    private fun artifact(
        volumeId: String = "volume",
        workId: String = SOURCE_WORK_ID,
        versionId: String = SOURCE_VERSION_ID,
    ) = CompletedDownloadArtifact(
        descriptor = DownloadDescriptor(
            identity = DownloadIdentity(namespace, workId, volumeId),
            workTitle = "Source Work",
            workAuthor = "Source Author",
            coverApiPath = "/api/works/$workId/cover",
            volumeTitle = "Volume",
            format = "EPUB",
            readerType = DownloadReaderType.Reflowable,
            source = DownloadSource("/api/volumes/$volumeId/file", "application/epub+zip", 10),
            versionId = versionId,
            versionSourceKey = "kindle",
            versionSourceName = "Kindle",
            versionCompleted = true,
        ),
        localReference = "local://$volumeId",
        verifiedBytes = 10,
        completedAtEpochMillis = 1,
    )

    private class FakeWorkManagementRepository(
        private val splitOutcome: WorkMutationOutcome? = null,
        private val transferOutcome: WorkMutationOutcome? = null,
        private val reclassifyOutcome: WorkMutationOutcome? = null,
    ) : WorkManagementRepository {
        override suspend fun supportsNativeManagement(context: WorkManagementContext) =
            WorkManagementResult.Content(true)

        override suspend fun splitVolume(
            context: WorkManagementContext,
            workId: String,
            volumeId: String,
            title: String,
            author: String?,
        ) = WorkManagementResult.Content(requireNotNull(splitOutcome))

        override suspend fun transferVolume(
            context: WorkManagementContext,
            workId: String,
            volumeId: String,
            targetWorkId: String,
        ) = WorkManagementResult.Content(requireNotNull(transferOutcome))

        override suspend fun reclassifyVolume(
            context: WorkManagementContext,
            workId: String,
            volumeId: String,
            mediaKind: ManagedMediaKind,
        ) = WorkManagementResult.Content(requireNotNull(reclassifyOutcome))

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

        override suspend fun deleteWork(context: WorkManagementContext, workId: String) = unused()

        override suspend fun updateVolume(
            context: WorkManagementContext,
            workId: String,
            volumeId: String,
            draft: VolumeMetadataDraft,
        ) = unused()

        override suspend fun deleteVolume(
            context: WorkManagementContext,
            workId: String,
            volumeId: String,
        ) = unused()

        override suspend fun searchTransferTargets(
            context: WorkManagementContext,
            workId: String,
            query: String,
        ) = unused()

        override suspend fun loadMetadataProviders(
            context: WorkManagementContext,
            mediaKind: ManagedMediaKind,
        ) = unused()

        override suspend fun searchMetadata(
            context: WorkManagementContext,
            workId: String,
            providerId: String,
            query: String,
        ) = unused()

        override suspend fun applyMetadata(
            context: WorkManagementContext,
            workId: String,
            providerId: String,
            candidate: MetadataCandidate,
            fields: Set<MetadataField>,
            volumeId: String?,
            applyToAllVolumes: Boolean,
        ) = unused()

        override suspend fun loadKindleSettings(context: WorkManagementContext) = unused()

        override suspend fun sendToKindle(
            context: WorkManagementContext,
            workId: String,
            fileId: String,
        ) = unused()

        override suspend fun setReadingStatus(
            context: WorkManagementContext,
            volumeId: String,
            status: ManagedReadingStatus,
        ) = unused()

        private fun unused(): Nothing = error("unused")
    }

    private companion object {
        const val SOURCE_WORK_ID = "work-source"
        const val SOURCE_VERSION_ID = "version-source"
        val namespace = DownloadNamespace("server", "user", 1)
        val context = WorkManagementContext(
            run {
                val parsed = ServerBaseUrl.parse("https://library.example") as ServerBaseUrlParseResult.Valid
                ServerProfile("profile", "Library", parsed.baseUrl, "server", true, TlsMode.SystemTrust)
            },
            PrivateDataNamespace("server", "user", 1),
        )
    }
}
