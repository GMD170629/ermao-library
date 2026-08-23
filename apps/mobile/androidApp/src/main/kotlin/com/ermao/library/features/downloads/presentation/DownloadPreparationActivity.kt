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
            resourceId = request.resourceId,
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
                    title = request.bookTitle,
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
                                bookId = artifact.bookId,
                                resourceId = artifact.resourceId,
                                assetId = artifact.assetId,
                                displayTitle = request.bookTitle,
                                localReference = artifact.localReference,
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
            bookId: String,
            bookTitle: String,
            author: String,
            coverApiPath: String,
            resourceId: String,
        ): Intent {
            require(profileId.isNotBlank() && bookId.isNotBlank() && bookTitle.isNotBlank() && resourceId.isNotBlank())
            return Intent(context, DownloadPreparationActivity::class.java)
                .putExtra(EXTRA_PROFILE_ID, profileId)
                .putExtra(EXTRA_BOOK_ID, bookId)
                .putExtra(EXTRA_BOOK_TITLE, bookTitle)
                .putExtra(EXTRA_AUTHOR, author)
                .putExtra(EXTRA_COVER_API_PATH, coverApiPath)
                .putExtra(EXTRA_RESOURCE_ID, resourceId)
                .addFlags(if (context is android.app.Activity) 0 else Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        private const val EXTRA_PROFILE_ID = "download.profile_id"
        private const val EXTRA_BOOK_ID = "download.book_id"
        private const val EXTRA_BOOK_TITLE = "download.book_title"
        private const val EXTRA_AUTHOR = "download.author"
        private const val EXTRA_COVER_API_PATH = "download.cover_api_path"
        private const val EXTRA_RESOURCE_ID = "download.resource_id"
    }

    private fun Intent.toRequest() = Request(
        profileId = checkNotNull(getStringExtra(EXTRA_PROFILE_ID)),
        bookId = checkNotNull(getStringExtra(EXTRA_BOOK_ID)),
        bookTitle = checkNotNull(getStringExtra(EXTRA_BOOK_TITLE)),
        author = getStringExtra(EXTRA_AUTHOR).orEmpty(),
        coverApiPath = checkNotNull(getStringExtra(EXTRA_COVER_API_PATH)),
        resourceId = checkNotNull(getStringExtra(EXTRA_RESOURCE_ID)),
    )

    private data class Request(
        val profileId: String,
        val bookId: String,
        val bookTitle: String,
        val author: String,
        val coverApiPath: String,
        val resourceId: String,
    )
}
