package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.audio.domain.AudioAsset
import com.ermao.library.shared.modules.audio.domain.AudioPublication
import com.ermao.library.shared.modules.audio.domain.AudioResource
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

/** Builds the shared identity projection for a platform-verified completed local artifact. */
class LocalAudioPublicationFactory {
    fun create(
        namespace: ReaderSyncNamespace,
        bookId: String,
        bookTitle: String,
        author: String?,
        resourceId: String,
        resourceTitle: String,
        assetId: String,
        mimeType: String,
        sizeBytes: Long,
        durationMillis: Long,
    ): AudioPublication {
        val sourceFormat = ReaderSourceFormat.entries.firstOrNull { format ->
            format.readerFormat == ReaderFormat.Audio && format.acceptsMimeType(mimeType)
        } ?: ReaderSourceFormat.Audio
        val resource = AudioResource(
            resourceId = resourceId,
            title = resourceTitle,
            sourceFormat = sourceFormat,
            sortOrder = 0,
            durationMillis = durationMillis.coerceAtLeast(0),
            trackCount = 1,
            chapterCount = 0,
        )
        return AudioPublication(
            namespace = namespace,
            bookId = bookId,
            bookTitle = bookTitle,
            author = author,
            coverApiPath = null,
            resource = resource,
            availableResources = listOf(resource),
            assets = listOf(
                AudioAsset(
                    assetId = assetId,
                    resourceId = resourceId,
                    title = resourceTitle,
                    apiPath = "/api/local-audio/artifact",
                    mimeType = mimeType,
                    sizeBytes = sizeBytes,
                    durationMillis = durationMillis.coerceAtLeast(0),
                    discNumber = null,
                    trackNumber = null,
                    sortOrder = 0,
                    codec = null,
                ),
            ),
            chapters = emptyList(),
        )
    }
}
