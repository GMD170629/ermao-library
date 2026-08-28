package com.ermao.library.features.reader.presentation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import com.ermao.library.ErmaoLibraryApplication
import com.ermao.library.R
import com.ermao.library.features.downloads.DownloadRecord
import com.ermao.library.features.downloads.DownloadStatus
import com.ermao.library.shared.modules.downloads.DownloadDescriptor
import com.ermao.library.shared.modules.downloads.DownloadRequestContext
import com.ermao.library.shared.modules.reader.ReaderAdmission
import java.text.NumberFormat

@Composable
internal fun ReaderDownloadTransition(
    descriptor: DownloadDescriptor,
    record: DownloadRecord?,
    failureCode: String?,
    preparing: Boolean,
    application: ErmaoLibraryApplication,
    context: DownloadRequestContext,
    onCancel: () -> Unit,
    onRetry: () -> Unit,
) {
    val hasFailure = failureCode != null || record?.status in setOf(DownloadStatus.FailedRetryable, DownloadStatus.FailedTerminal)
    val received = record?.transferredBytes ?: 0L
    val total = record?.expectedBytes ?: descriptor.totalBytes
    val progress = ReaderAdmission.progress(received, total)
    val locale = LocalConfiguration.current.locales[0]
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally) {
        com.ermao.library.features.content.CatalogBookCover(
            descriptor.identity.bookId, descriptor.bookTitle, descriptor.coverApiPath.orEmpty(),
            application.contentRepository,
            com.ermao.library.shared.modules.library.ContentRequestContext(context.profile,
                com.ermao.library.shared.modules.auth.domain.PrivateDataNamespace(context.namespace.serverIdentity,
                    context.namespace.userId, context.namespace.authorizationVersion)),
            Modifier.size(120.dp, 168.dp), managementEnabled = false,
        )
        Text(descriptor.bookTitle, style = MaterialTheme.typography.titleLarge)
        Text(stringResource(R.string.reader_download_reason))
        if (hasFailure) Text(com.ermao.library.features.downloads.downloadFailureMessage(failureCode ?: record?.errorCode))
        Text(stringResource(when {
            preparing -> R.string.reader_download_preparing
            hasFailure -> R.string.reader_download_failed
            record?.status == DownloadStatus.Downloading -> R.string.reader_download_transferring
            record?.status == DownloadStatus.Paused -> R.string.reader_download_paused
            else -> R.string.reader_download_queued
        }))
        if (!preparing) {
            LinearProgressIndicator(progress = { progress.toFloat() })
            Text(stringResource(R.string.reader_download_bytes, NumberFormat.getIntegerInstance(locale).format(received),
                NumberFormat.getIntegerInstance(locale).format(total), NumberFormat.getPercentInstance(locale).format(progress)))
        }
        if (hasFailure || record?.status == DownloadStatus.Paused) {
            Button(onClick = onRetry) { Text(stringResource(R.string.reader_download_retry)) }
        }
        Button(onClick = onCancel) { Text(stringResource(R.string.reader_download_cancel)) }
    }
}
