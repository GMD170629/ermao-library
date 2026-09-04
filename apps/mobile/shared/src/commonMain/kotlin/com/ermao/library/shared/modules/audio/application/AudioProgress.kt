package com.ermao.library.shared.modules.audio.application

import com.ermao.library.shared.modules.audio.domain.AudioPublication
import com.ermao.library.shared.modules.reader.AudioReaderLocation
import com.ermao.library.shared.modules.reader.ReaderChapterPresentation
import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import com.ermao.library.shared.modules.reader.ReaderPlaybackPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionLocalState
import com.ermao.library.shared.modules.reader.ReaderPositionPresentation
import com.ermao.library.shared.modules.reader.ReaderPositionReport
import com.ermao.library.shared.modules.reader.ReaderPositionSyncRuntime
import com.ermao.library.shared.modules.reader.ReaderProgressSnapshotV5
import com.ermao.library.shared.modules.reader.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.ReaderLocationRestoreException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

enum class AudioProgressSaveReason {
    Tick,
    Seek,
    Pause,
    ChapterChange,
    TrackChange,
    Stop,
    Background,
    Completed,
}

/** Persists audio captures through the v5 latest-only position store. */
class AudioProgressWriter(
    private val store: com.ermao.library.shared.modules.reader.ReaderPositionSyncingStore,
    private val resourceId: String,
    private val deviceId: String,
    private val nowEpochMillis: () -> Long,
) {
    suspend fun save(
        assetId: String,
        chapterId: String?,
        positionMillis: Long,
        durationMillis: Long?,
        reason: AudioProgressSaveReason,
        mimeType: String = "audio/mp4",
        logicalPosition: Int = 1,
        /** The engine/publication href carried in the Locator; defaults to the stable asset id. */
        locatorHref: String = assetId,
        absolutePositionMillis: Long? = null,
        totalDurationMillis: Long? = null,
        currentAssetIndex: Int? = null,
        chapterIndex: Int? = null,
        chapterTitle: String? = null,
    ): ReaderPositionLocalState {
        val now = nowEpochMillis()
        require(now >= 0 && positionMillis >= 0)
        require(durationMillis == null || durationMillis >= 0)
        require(absolutePositionMillis == null || absolutePositionMillis >= 0)
        require(totalDurationMillis == null || totalDurationMillis >= 0)
        require(currentAssetIndex == null || currentAssetIndex >= 0)
        require(chapterIndex == null || chapterIndex >= 0)
        require(chapterTitle == null || chapterTitle.isNotBlank())
        require(mimeType.isNotBlank())
        require(logicalPosition >= 1)
        require(locatorHref.isNotBlank())
        val trackProgression = durationMillis
            ?.takeIf { it > 0 }
            ?.let { duration -> positionMillis.coerceAtMost(duration).toDouble() / duration.toDouble() }
            ?: 0.0
        val captureAbsolute = absolutePositionMillis ?: positionMillis
        val captureTotal = totalDurationMillis ?: durationMillis
        val totalProgression = captureTotal
            ?.takeIf { it > 0 }
            ?.let { total -> captureAbsolute.coerceAtMost(total).toDouble() / total.toDouble() }
            ?: trackProgression
        val captureLogicalPosition = currentAssetIndex?.plus(1) ?: logicalPosition
        val report = ReaderPositionReport(
            locator = ReaderOpaqueLocator.parse(
                "{\"href\":${jsonString(locatorHref)},\"type\":${jsonString(mimeType)}," +
                    "\"locations\":{\"position\":$captureLogicalPosition,\"progression\":$trackProgression," +
                    "\"totalProgression\":$totalProgression,\"time\":${positionMillis.toDouble() / 1000.0}}}",
            ),
            presentation = ReaderPositionPresentation(
                displayPercent = totalProgression * 100.0,
                totalProgression = totalProgression,
                currentHref = locatorHref,
                chapter = if (chapterId != null || chapterIndex != null || chapterTitle != null) {
                    ReaderChapterPresentation(href = locatorHref, title = chapterTitle, index = chapterIndex)
                } else {
                    null
                },
                page = null,
                playback = ReaderPlaybackPresentation(positionMillis, durationMillis),
            ),
        )
        val state = ReaderPositionLocalState(resourceId, deviceId, now, report)
        store.save(state)
        return state
    }

    /** Persists the complete publication snapshot carried by one shared effect. */
    suspend fun save(effect: AudioPlaybackEffect): ReaderPositionLocalState {
        require(effect.type == AudioPlaybackEffectType.SaveProgress)
        val asset = requireNotNull(effect.asset)
        val reason = requireNotNull(effect.progressReason)
        return save(
            assetId = asset.assetId,
            chapterId = effect.chapterId,
            positionMillis = effect.positionMillis,
            durationMillis = effect.durationMillis,
            reason = reason,
            mimeType = asset.mimeType,
            logicalPosition = effect.currentAssetIndex + 1,
            locatorHref = asset.apiPath,
            absolutePositionMillis = effect.absolutePositionMillis,
            totalDurationMillis = effect.totalDurationMillis,
            currentAssetIndex = effect.currentAssetIndex,
            chapterIndex = effect.chapterIndex,
            chapterTitle = effect.chapterTitle,
        )
    }

    suspend fun restore(): ReaderPositionReport? = store.load(resourceId)?.position

    /** Audio adapter projection: only the opaque Locator chooses the engine asset/time. */
    fun toAudioLocation(report: ReaderPositionReport): AudioReaderLocation? = runCatching {
        val root = Json.parseToJsonElement(report.locator.canonicalJson).jsonObject
        val assetId = (root["href"] as? kotlinx.serialization.json.JsonPrimitive)
            ?.takeIf { it.isString }?.content?.takeIf(String::isNotBlank) ?: return null
        val locations = (root["locations"] as? JsonObject)
        val timeSeconds = locations?.get("time")
            ?.let { (it as? kotlinx.serialization.json.JsonPrimitive)
                ?.takeIf { primitive -> !primitive.isString }
                ?.doubleOrNull }
        val positionMillis = timeSeconds
            ?.takeIf { it.isFinite() && it >= 0.0 && it <= Long.MAX_VALUE / 1000.0 }
            ?.let { (it * 1000.0).toLong() }
            ?: return null
        AudioReaderLocation(assetId, null, positionMillis.coerceAtLeast(0))
    }.getOrNull()

    suspend fun restoreProgress(): ReaderPositionLocalState? = store.load(resourceId)
}

/** Shared audio restore/persistence use case backed by the v5 position runtime. */
class AudioProgressSession(
    private val writer: AudioProgressWriter,
    private val syncRuntime: ReaderPositionSyncRuntime? = null,
    private val syncTarget: ReaderProgressSyncTarget? = null,
) {
    private val mutex = Mutex()

    init {
        require((syncRuntime == null) == (syncTarget == null))
    }

    suspend fun restore(
        publication: AudioPublication,
        remoteSnapshot: ReaderProgressSnapshotV5?,
    ): AudioReaderLocation? = mutex.withLock {
        val hasPendingLocal = syncRuntime?.store?.syncState()?.pending != null
        val candidate = if (hasPendingLocal) {
            writer.restoreProgress()?.position
                ?: throw ReaderLocationRestoreException()
        } else {
            remoteSnapshot?.position
        } ?: return@withLock null

        val location = writer.toAudioLocation(candidate)
            ?: throw ReaderLocationRestoreException()
        location.normalizeFor(publication)
            ?: throw ReaderLocationRestoreException()
    }

    /** Decodes one selected server snapshot without consulting or replacing the local outbox. */
    suspend fun remoteLocation(
        publication: AudioPublication,
        snapshot: ReaderProgressSnapshotV5,
    ): AudioReaderLocation = mutex.withLock {
        writer.toAudioLocation(snapshot.position)
            ?.normalizeFor(publication)
            ?: throw ReaderLocationRestoreException()
    }

    /** Accepts the exact server report only after the audio engine accepted the requested seek. */
    suspend fun acceptRemote(
        snapshot: ReaderProgressSnapshotV5,
        clientId: String,
    ) = mutex.withLock {
        val runtime = requireNotNull(syncRuntime)
        runtime.coordinator.acceptRemotePosition(
            ReaderPositionLocalState(
                resourceId = snapshot.resourceId,
                clientId = clientId,
                capturedAtEpochMillis = snapshot.capturedAtEpochMillis,
                position = snapshot.position,
            ),
            snapshot,
        )
    }

    suspend fun save(
        assetId: String,
        chapterId: String?,
        positionMillis: Long,
        durationMillis: Long?,
        reason: AudioProgressSaveReason,
    ) = mutex.withLock {
        writer.save(assetId, chapterId, positionMillis, durationMillis, reason)
    }

    suspend fun save(effect: AudioPlaybackEffect) = mutex.withLock {
        writer.save(effect)
    }
}

private fun AudioReaderLocation.isValidFor(publication: AudioPublication): Boolean =
    publication.assets.any { it.assetId == assetId } && positionMillis >= 0

private fun AudioReaderLocation.normalizeFor(publication: AudioPublication): AudioReaderLocation? {
    val asset = publication.assets.firstOrNull { asset ->
        asset.assetId == assetId || asset.apiPath == assetId
    } ?: return null
    return copy(assetId = asset.assetId).takeIf { it.isValidFor(publication) }
}

private fun jsonString(value: String): String = buildString {
    append('"')
    value.forEach { character ->
        when (character) {
            '\\' -> append("\\\\")
            '"' -> append("\\\"")
            '\n' -> append("\\n")
            '\r' -> append("\\r")
            '\t' -> append("\\t")
            else -> append(character)
        }
    }
    append('"')
}
