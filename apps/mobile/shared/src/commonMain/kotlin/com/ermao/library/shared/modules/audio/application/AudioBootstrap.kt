package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.audio.domain.AudioAsset
import com.ermao.library.shared.modules.audio.domain.AudioChapter
import com.ermao.library.shared.modules.audio.domain.AudioPublication
import com.ermao.library.shared.modules.audio.domain.AudioResource
import com.ermao.library.shared.modules.reader.ReaderBootstrap
import com.ermao.library.shared.modules.reader.ReaderBootstrapGateway
import com.ermao.library.shared.modules.reader.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.ReaderBootstrapContent
import com.ermao.library.shared.modules.reader.ReaderBootstrapFailure
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderSafetyBudgetName
import com.ermao.library.shared.modules.reader.ReaderSafetyPolicy

sealed interface AudioBootstrapResult {
    data class Content(val publication: AudioPublication, val bootstrap: ReaderBootstrap) : AudioBootstrapResult
    data class Failure(val code: String, val recoverable: Boolean) : AudioBootstrapResult {
        init {
            require(code.isNotBlank())
        }
    }
}

/** Audio projection of the existing Reader v4 bootstrap; it does not create a second HTTP contract. */
class LoadAudioPublication(
    private val gateway: ReaderBootstrapGateway,
) {
    suspend fun execute(request: ReaderBootstrapRequest): AudioBootstrapResult =
        when (val result = gateway.load(request)) {
            is ReaderBootstrapFailure -> AudioBootstrapResult.Failure(
                result.failureCode,
                result.recoverable,
            )
            is ReaderBootstrapContent -> result.value.toAudioPublication()
        }
}

private fun ReaderBootstrap.toAudioPublication(): AudioBootstrapResult {
    if (target.sourceFormat != ReaderFormat.Audio || resource.sourceFormat.readerFormat != ReaderFormat.Audio) {
        return AudioBootstrapResult.Failure("AUDIO_BOOTSTRAP_REQUIRED", recoverable = false)
    }
    val trackLimit = ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.AUDIO_TRACK_MAX_COUNT)
    val chapterLimit = ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.AUDIO_CHAPTER_MAX_COUNT)
    if (assets.isEmpty()) return AudioBootstrapResult.Failure("READER_PUBLICATION_ASSET_MISSING", false)
    if (assets.size.toLong() > trackLimit || units.size.toLong() > chapterLimit) {
        return AudioBootstrapResult.Failure("AUDIO_DURATION_INVALID", false)
    }
    val audioAssets = assets.map { asset ->
        if (!resource.sourceFormat.acceptsMimeType(asset.mimeType)) {
            return AudioBootstrapResult.Failure("AUDIO_MIME_MISMATCH", false)
        }
        AudioAsset(
            assetId = asset.assetId,
            resourceId = asset.resourceId,
            title = asset.title,
            apiPath = asset.apiPath,
            mimeType = asset.mimeType,
            sizeBytes = asset.sizeBytes,
            durationMillis = asset.durationMillis,
            discNumber = asset.discNumber,
            trackNumber = asset.trackNumber,
            sortOrder = asset.sortOrder,
            codec = asset.codec,
        )
    }
    val audioChapters = try {
        units.map { unit ->
            val assetId = unit.assetId ?: audioAssets.singleOrNull()?.assetId
                ?: throw IllegalArgumentException("A chapter in a multi-track publication requires an Asset")
            val start = unit.startMs ?: 0L
            val end = unit.endMs ?: unit.durationMs?.let { duration -> start + duration }
            val asset = audioAssets.firstOrNull { it.assetId == assetId }
                ?: throw IllegalArgumentException("Audio chapter references an unknown Asset")
            val assetDuration = asset.durationMillis
            require(end == null || end >= start)
            require(assetDuration == null || start <= assetDuration)
            require(assetDuration == null || end == null || end <= assetDuration)
            AudioChapter(
                chapterId = unit.id,
                assetId = assetId,
                index = unit.index,
                title = unit.title,
                startMillis = start,
                endMillis = end,
            )
        }
    } catch (_: IllegalArgumentException) {
        return AudioBootstrapResult.Failure("AUDIO_DURATION_INVALID", false)
    }
    val publication = AudioPublication(
        namespace = target.namespace,
        bookId = book.bookId,
        bookTitle = book.title,
        author = book.author,
        coverApiPath = book.coverApiPath,
        resource = resource.toAudioResource(),
        availableResources = availableResources
            .filter { it.sourceFormat.readerFormat == ReaderFormat.Audio }
            .map { it.toAudioResource() },
        assets = audioAssets,
        chapters = audioChapters,
    )
    return AudioBootstrapResult.Content(publication, this)
}

private fun com.ermao.library.shared.modules.reader.ReaderBootstrapResource.toAudioResource() = AudioResource(
    resourceId = resourceId,
    title = displayTitle,
    sourceFormat = sourceFormat,
    sortOrder = sortOrder,
    durationMillis = durationMillis,
    trackCount = trackCount,
    chapterCount = chapterCount,
)
