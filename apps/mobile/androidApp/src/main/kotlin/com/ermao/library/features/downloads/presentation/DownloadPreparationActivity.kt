package com.ermao.library.features.downloads.presentation

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.addCallback
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.features.downloads.application.DownloadPreparationViewModel
import com.ermao.library.features.downloads.ui.DownloadPreparationScreen
import com.ermao.library.features.reader.presentation.ReaderActivity
import com.ermao.library.platform.persistence.AndroidCoverCache
import com.ermao.library.shared.core.network.AndroidEncryptedCookieVault
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.downloads.createDownloadsGateway
import com.ermao.library.shared.modules.downloads.toDownloadNamespace
import com.ermao.library.shared.modules.library.ContentRequestContext
import com.ermao.library.ui.theme.WarmPageTheme
import kotlinx.coroutines.launch

class DownloadPreparationActivity : AppCompatActivity() {
    private val request by lazy { intent.toRequest() }
    private val preparationViewModel: DownloadPreparationViewModel by viewModels {
        val application = application as ErmaoLibraryApplication
        val session = application.mobileRuntime.currentSession as? AppSession.Authenticated
            ?: error("An authenticated session is required to prepare a download")
        require(session.profile.id == request.profileId)
        val downloadsGateway = createDownloadsGateway(
            ApiClientFactory(AndroidEncryptedCookieVault(applicationContext), requestTimeoutMillis = 30L * 60L * 1000L),
            session.profile,
        )
        DownloadPreparationViewModel.factory(
            volumeId = request.volumeId,
            context = DownloadRequestContext(session.profile, session.identity.namespace.toDownloadNamespace()),
            catalog = application.sharedDownloadCatalog,
            sink = application.downloadFiles,
            bootstrapGateway = downloadsGateway,
            transferGateway = downloadsGateway,
        )
    }
    private var readerOpened = false
    private var coverBytes by mutableStateOf<ByteArray?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val application = application as ErmaoLibraryApplication
        val session = application.mobileRuntime.currentSession as? AppSession.Authenticated
        if (session == null || session.profile.id != request.profileId) {
            finish()
            return
        }
        onBackPressedDispatcher.addCallback(this) {
            preparationViewModel.cancel(::finish)
        }
        lifecycleScope.launch {
            coverBytes = AndroidCoverCache.load(
                applicationContext,
                ContentRequestContext(session.profile, session.identity.namespace),
                request.coverApiPath,
                application.contentRepository,
            )
        }
        setContent {
            WarmPageTheme {
                val state by preparationViewModel.uiState.collectAsStateWithLifecycle()
                DownloadPreparationScreen(
                    title = request.workTitle,
                    author = request.author,
                    coverBytes = coverBytes,
                    state = state,
                    onRetry = preparationViewModel::retry,
                    onCancel = { preparationViewModel.cancel(::finish) },
                )
                LaunchedEffect(preparationViewModel) {
                    preparationViewModel.completed.collect { artifact ->
                        if (readerOpened) return@collect
                        readerOpened = true
                        startActivity(
                            ReaderActivity.createManagedDownloadIntent(
                                context = this@DownloadPreparationActivity,
                                profileId = request.profileId,
                                workId = request.workId,
                                volumeId = request.volumeId,
                                displayTitle = request.workTitle,
                                localReference = artifact.localReference,
                                serverContentFingerprint = artifact.contentFingerprint,
                                expectedBytes = artifact.expectedBytes,
                                sourceFormat = artifact.format,
                            ),
                        )
                        finish()
                    }
                }
            }
        }
    }

    companion object {
        fun createIntent(
            context: Context,
            profileId: String,
            workId: String,
            workTitle: String,
            author: String,
            coverApiPath: String,
            volumeId: String,
        ): Intent {
            require(profileId.isNotBlank() && workId.isNotBlank() && workTitle.isNotBlank() && volumeId.isNotBlank())
            return Intent(context, DownloadPreparationActivity::class.java)
                .putExtra(EXTRA_PROFILE_ID, profileId)
                .putExtra(EXTRA_WORK_ID, workId)
                .putExtra(EXTRA_WORK_TITLE, workTitle)
                .putExtra(EXTRA_AUTHOR, author)
                .putExtra(EXTRA_COVER_API_PATH, coverApiPath)
                .putExtra(EXTRA_VOLUME_ID, volumeId)
                .addFlags(if (context is android.app.Activity) 0 else Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        private const val EXTRA_PROFILE_ID = "download.profile_id"
        private const val EXTRA_WORK_ID = "download.work_id"
        private const val EXTRA_WORK_TITLE = "download.work_title"
        private const val EXTRA_AUTHOR = "download.author"
        private const val EXTRA_COVER_API_PATH = "download.cover_api_path"
        private const val EXTRA_VOLUME_ID = "download.volume_id"
    }

    private fun Intent.toRequest() = Request(
        profileId = checkNotNull(getStringExtra(EXTRA_PROFILE_ID)),
        workId = checkNotNull(getStringExtra(EXTRA_WORK_ID)),
        workTitle = checkNotNull(getStringExtra(EXTRA_WORK_TITLE)),
        author = getStringExtra(EXTRA_AUTHOR).orEmpty(),
        coverApiPath = checkNotNull(getStringExtra(EXTRA_COVER_API_PATH)),
        volumeId = checkNotNull(getStringExtra(EXTRA_VOLUME_ID)),
    )

    private data class Request(
        val profileId: String,
        val workId: String,
        val workTitle: String,
        val author: String,
        val coverApiPath: String,
        val volumeId: String,
    )
}
