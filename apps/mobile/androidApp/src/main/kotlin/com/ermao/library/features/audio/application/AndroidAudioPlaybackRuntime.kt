package com.ermao.library.features.audio.application

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.ermao.library.features.audio.infrastructure.AndroidAudioPlaybackService
import com.ermao.library.features.audio.infrastructure.AndroidAudioTransportRegistry
import com.ermao.library.features.audio.model.AndroidAudioChapter
import com.ermao.library.features.audio.model.AndroidAudioError
import com.ermao.library.features.audio.model.AndroidAudioLaunchIntent
import com.ermao.library.features.audio.model.AndroidAudioNamespace
import com.ermao.library.features.audio.model.AndroidAudioPhase
import com.ermao.library.features.audio.model.AndroidAudioPlaybackSnapshot
import com.ermao.library.features.audio.model.AndroidAudioTrack
import com.ermao.library.features.audio.model.DEFAULT_PLAYBACK_RATE
import com.ermao.library.features.audio.model.SUPPORTED_PLAYBACK_RATES
import com.ermao.library.shared.modules.audio.AudioLaunchIntent
import com.ermao.library.shared.modules.audio.AudioMediaTransport
import com.ermao.library.shared.modules.audio.AudioBootstrapContent
import com.ermao.library.shared.modules.audio.AudioBootstrapFailure
import com.ermao.library.shared.modules.audio.AudioProgressSaveReason
import com.ermao.library.shared.modules.audio.AudioProgressWriter
import com.ermao.library.shared.modules.audio.AudioPlaybackStateMachine
import com.ermao.library.shared.modules.audio.LoadAudioPublication
import com.ermao.library.shared.modules.reader.ReaderFormat
import com.ermao.library.shared.modules.reader.ReaderBootstrapGateway
import com.ermao.library.shared.modules.reader.ReaderBootstrapRequest
import com.ermao.library.shared.modules.reader.ReaderLocalProgressIdentity
import com.ermao.library.shared.modules.reader.ReaderProgressSyncTarget
import com.ermao.library.shared.modules.reader.ReaderProgressSyncRuntime
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.createAndroidReaderProgressSyncPort
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.features.reader.infrastructure.AndroidReaderDeviceIdentity
import com.ermao.library.features.reader.infrastructure.AndroidReaderProgressDatabase
import java.io.Closeable
import java.io.File
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * A small application port around the process-wide Media3 controller.
 *
 * KMP owns launch intent validation, bootstrap, progress outbox and namespace decisions. This
 * runtime only maps that public contract to a service-backed Android player and reports engine
 * observations back through [progressSink].
 */
class AndroidAudioPlaybackRuntime(
    context: Context,
    private val transportRegistry: AndroidAudioTransportRegistry? = null,
    private val progressSink: AndroidAudioProgressSink = AndroidAudioProgressSink.NoOp,
) : Closeable {
    private val appContext = context.applicationContext
    private val mainExecutor: Executor = appContext.mainExecutor
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val generation = AtomicLong(0)
    private val sharedStateMachine = AudioPlaybackStateMachine()
    private val _snapshot = MutableStateFlow(AndroidAudioPlaybackSnapshot())

    private var controller: MediaController? = null
    private var controllerFuture: com.google.common.util.concurrent.ListenableFuture<MediaController>? = null
    private var pendingLaunch: AndroidAudioLaunchIntent? = null
    private var activeIntent: AndroidAudioLaunchIntent? = null
    private var progressJob: Job? = null
    private var lastError: AndroidAudioError? = null
    private var remoteLaunch: RemoteLaunch? = null
    private var activePublication: com.ermao.library.shared.modules.audio.AudioPublication? = null
    private var sharedSessionId: Long? = null
    private var activeProgressRuntime: ReaderProgressSyncRuntime? = null
    private var activeProgressWriter: AudioProgressWriter? = null

    val snapshot: StateFlow<AndroidAudioPlaybackSnapshot> = _snapshot.asStateFlow()

    init {
        connect()
    }

    /** Starts a single namespace-scoped session. A new launch supersedes the old session. */
    fun launch(intent: AndroidAudioLaunchIntent) {
        val launchGeneration = generation.incrementAndGet()
        remoteLaunch = null
        if (activePublication == null || sharedSessionId == null) {
            sharedStateMachine.retireSession()
            sharedSessionId = null
        }
        pendingLaunch = intent
        activeIntent = intent
        lastError = null
        progressJob?.cancel()
        progressJob = null
        _snapshot.value = intent.toSnapshot(AndroidAudioPhase.Loading)
        val connected = controller
        if (connected != null) {
            applyLaunch(connected, intent, launchGeneration)
        }
    }

    /** Starts a verified completed local artifact without creating an online fallback request. */
    fun launchLocal(
        namespace: AndroidAudioNamespace,
        bookId: String,
        resourceId: String,
        title: String,
        author: String?,
        assetId: String,
        localFile: File,
        mimeType: String,
        positionMillis: Long = 0,
    ) {
        require(localFile.isFile && localFile.length() > 0) { "AUDIO_LOCAL_ARTIFACT_UNAVAILABLE" }
        launch(
            AndroidAudioLaunchIntent(
                namespace = namespace,
                bookId = bookId,
                resourceId = resourceId,
                title = title,
                author = author,
                tracks = listOf(
                    AndroidAudioTrack(
                        assetId = assetId,
                        title = title,
                        sourceUri = localFile.toURI().toString(),
                        mimeType = mimeType,
                        durationMillis = null,
                    ),
                ),
                assetId = assetId,
                positionMillis = positionMillis,
                autoplay = true,
            ),
        )
    }

    /**
     * Loads the existing Reader v4 bootstrap and projects it through the shared Audio capability.
     * The current engine remains untouched while a replacement resource is loading; a failed
     * replacement therefore cannot blank an otherwise valid playing session.
     */
    fun launchRemote(
        profile: ServerProfile,
        namespace: ReaderSyncNamespace,
        resourceId: String,
        chapterId: String? = null,
        positionMillis: Long? = null,
        titleHint: String? = null,
        artworkUri: String? = null,
        autoplay: Boolean = true,
        bootstrapGateway: ReaderBootstrapGateway,
        mediaTransport: AudioMediaTransport,
    ) {
        require(profile.serverIdentity == namespace.serverIdentity)
        val token = generation.incrementAndGet()
        val request = RemoteLaunch(
            token = token,
            profile = profile,
            namespace = namespace,
            resourceId = resourceId,
            chapterId = chapterId,
            positionMillis = positionMillis,
            titleHint = titleHint,
            artworkUri = artworkUri,
            autoplay = autoplay,
            bootstrapGateway = bootstrapGateway,
            mediaTransport = mediaTransport,
        )
        remoteLaunch = request
        if (!snapshot.value.hasSession) {
            _snapshot.value = AndroidAudioPlaybackSnapshot(
                phase = AndroidAudioPhase.Loading,
                namespace = AndroidAudioNamespace(
                    namespace.serverIdentity,
                    namespace.userId,
                    namespace.authorizationVersion,
                ),
                resourceId = resourceId,
                title = titleHint,
            )
        }
        scope.launch {
            val result = runCatching {
                LoadAudioPublication(bootstrapGateway).execute(
                    ReaderBootstrapRequest(profile, namespace, resourceId),
                )
            }.getOrElse {
                AudioBootstrapFailure("AUDIO_NETWORK_UNAVAILABLE", recoverable = true)
            }
            if (generation.get() != token || remoteLaunch !== request) return@launch
            when (result) {
                is AudioBootstrapContent -> {
                    val publication = result.publication
                    val sourceUris = publication.assets.associate { asset ->
                        profile.baseUrl.resolveApiPath(asset.apiPath) to asset
                    }
                    transportRegistry?.register(namespace.stableKey, mediaTransport, sourceUris)
                    val intent = AudioLaunchIntent(
                        resourceId = resourceId,
                        assetId = requestAssetId(publication, request.chapterId),
                        chapterId = request.chapterId,
                        positionMillis = request.positionMillis,
                        autoplay = autoplay,
                    )
                    configureProgress(publication, profile)
                    val mapped = AndroidAudioLaunchIntent.fromPublication(
                        publication = publication,
                        intent = intent,
                        sourceUriForAsset = { asset -> profile.baseUrl.resolveApiPath(asset.apiPath) },
                        artworkUri = artworkUri,
                    )
                    activePublication = publication
                    commitSharedPublication(publication, intent)
                    remoteLaunch = null
                    launch(mapped)
                }
                is AudioBootstrapFailure -> {
                    if (!snapshot.value.hasSession) {
                        _snapshot.value = AndroidAudioPlaybackSnapshot(
                            phase = AndroidAudioPhase.Error,
                            namespace = AndroidAudioNamespace(
                                namespace.serverIdentity,
                                namespace.userId,
                                namespace.authorizationVersion,
                            ),
                            resourceId = resourceId,
                            title = titleHint,
                            error = AndroidAudioError(result.code, result.recoverable),
                        )
                    }
                }
            }
        }
    }

    fun play() {
        controller?.play()
    }

    fun pause() {
        controller?.pause()
        captureProgress(immediate = true, reason = AudioProgressSaveReason.Pause)
    }

    /** App-owned stop: save first, then release the current queue and clear the mini player. */
    fun stop() {
        captureProgress(immediate = true, reason = AudioProgressSaveReason.Stop)
        pendingLaunch = null
        activeIntent = null
        remoteLaunch = null
        progressJob?.cancel()
        progressJob = null
        controller?.run {
            stop()
            clearMediaItems()
        }
        _snapshot.value.namespace?.key?.let { transportRegistry?.remove(it) }
        activePublication = null
        sharedStateMachine.retireSession()
        sharedSessionId = null
        _snapshot.value = AndroidAudioPlaybackSnapshot()
    }

    fun seekTo(positionMillis: Long) {
        val controller = controller ?: return
        val duration = controller.duration.takeIf { it > 0 }
        val target = positionMillis.coerceAtLeast(0).let { value -> duration?.let(value::coerceAtMost) ?: value }
        controller.seekTo(target)
        publishFromController()
        captureProgress(immediate = true, reason = AudioProgressSaveReason.Seek)
    }

    fun skipBack() = seekTo((controller?.currentPosition ?: snapshot.value.positionMillis) - BACK_SKIP_MILLIS)

    fun skipForward() = seekTo((controller?.currentPosition ?: snapshot.value.positionMillis) + FORWARD_SKIP_MILLIS)

    fun previous() {
        val current = currentTrackAndChapter() ?: return
        val chapters = current.second.chapters
        val chapterIndex = chapters.indexOfFirst { it.id == snapshot.value.chapterId }
        if (chapterIndex > 0) {
            seekTo(chapters[chapterIndex - 1].startMillis)
            updateChapter(chapters[chapterIndex - 1])
        } else if (snapshot.value.positionMillis > PREVIOUS_CHAPTER_THRESHOLD_MILLIS && chapterIndex >= 0) {
            seekTo(chapters[chapterIndex].startMillis)
            updateChapter(chapters[chapterIndex])
        } else if (controller?.hasPreviousMediaItem() == true) {
            controller?.seekToPreviousMediaItem()
        } else {
            seekTo(0)
        }
    }

    fun next() {
        val current = currentTrackAndChapter() ?: return
        val chapters = current.second.chapters
        val chapterIndex = chapters.indexOfFirst { it.id == snapshot.value.chapterId }
        val nextChapter = chapters.getOrNull(chapterIndex + 1)
        if (nextChapter != null) {
            seekTo(nextChapter.startMillis)
            updateChapter(nextChapter)
        } else if (controller?.hasNextMediaItem() == true) {
            controller?.seekToNextMediaItem()
        } else {
            controller?.seekTo(0)
            controller?.pause()
        }
    }

    fun selectChapter(chapterId: String) {
        val current = currentTrackAndChapter() ?: return
        val chapter = current.second.chapters.firstOrNull { it.id == chapterId } ?: return
        seekTo(chapter.startMillis)
        updateChapter(chapter)
    }

    fun selectAsset(assetId: String) {
        val intent = activeIntent ?: return
        val trackIndex = intent.tracks.indexOfFirst { it.assetId == assetId }
        if (trackIndex < 0) return
        val controller = controller ?: return
        val updated = intent.copy(assetId = assetId, chapterId = null, positionMillis = 0)
        activeIntent = updated
        generation.incrementAndGet()
        controller.seekToDefaultPosition(trackIndex)
        controller.prepare()
        publishFromController()
    }

    fun setPlaybackRate(rate: Float) {
        val selected = SUPPORTED_PLAYBACK_RATES.firstOrNull { it == rate } ?: return
        controller?.setPlaybackParameters(PlaybackParameters(selected))
        _snapshot.value = _snapshot.value.copy(playbackRate = selected)
    }

    /** Re-attempts the current launch after a recoverable source or network error. */
    fun retry() {
        remoteLaunch?.let { request ->
            launchRemote(
                profile = request.profile,
                namespace = request.namespace,
                resourceId = request.resourceId,
                chapterId = request.chapterId,
                positionMillis = request.positionMillis,
                titleHint = request.titleHint,
                artworkUri = request.artworkUri,
                autoplay = request.autoplay,
                bootstrapGateway = request.bootstrapGateway,
                mediaTransport = request.mediaTransport,
            )
            return
        }
        val intent = activeIntent ?: pendingLaunch ?: return
        launch(intent.copy(autoplay = true))
    }

    /** The queue is exposed as immutable adapter data for the chapter/track sheet only. */
    fun currentTracks(): List<AndroidAudioTrack> = activeIntent?.tracks.orEmpty()

    /** Called by the host when an active account/server namespace is no longer valid. */
    fun invalidateNamespace(namespace: AndroidAudioNamespace) {
        if (_snapshot.value.namespace?.key == namespace.key) stop()
    }

    override fun close() {
        stop()
        controllerFuture?.let { MediaController.releaseFuture(it) }
        controllerFuture = null
        controller?.release()
        controller = null
        activeProgressRuntime?.close()
        activeProgressRuntime = null
        activeProgressWriter = null
        scope.coroutineContext.cancel()
    }

    private fun connect() {
        val token = SessionToken(
            appContext,
            ComponentName(appContext, AndroidAudioPlaybackService::class.java),
        )
        val future = MediaController.Builder(appContext, token).buildAsync()
        controllerFuture = future
        future.addListener(
            {
                val connected = runCatching { future.get() }.getOrNull() ?: return@addListener
                if (controllerFuture !== future) {
                    connected.release()
                    return@addListener
                }
                controller = connected
                connected.addListener(ControllerListener())
                pendingLaunch?.let { launch(it) }
                publishFromController()
            },
            mainExecutor,
        )
    }

    private fun applyLaunch(
        controller: MediaController,
        intent: AndroidAudioLaunchIntent,
        launchGeneration: Long,
    ) {
        if (generation.get() != launchGeneration || activeIntent !== intent) return
        val mediaItems = intent.tracks.map { track -> track.toMediaItem(intent) }
        val selectedIndex = intent.tracks.indexOfFirst { it.assetId == intent.assetId }.takeIf { it >= 0 } ?: 0
        controller.setMediaItems(mediaItems, selectedIndex, intent.positionMillis)
        controller.setPlaybackParameters(PlaybackParameters(DEFAULT_PLAYBACK_RATE))
        controller.prepare()
        if (intent.autoplay) controller.play() else controller.pause()
        pendingLaunch = null
        publishFromController()
        if (intent.autoplay) startProgressTicker()
    }

    private fun commitSharedPublication(
        publication: com.ermao.library.shared.modules.audio.AudioPublication,
        intent: AudioLaunchIntent,
    ) {
        val pending = sharedStateMachine.beginLaunch(publication.namespace, intent)
        check(sharedStateMachine.commitLaunch(pending.token, publication)) {
            "AUDIO_SHARED_SESSION_COMMIT_REJECTED"
        }
        sharedSessionId = pending.token
    }

    private fun startProgressTicker() {
        if (progressJob?.isActive == true) return
        progressJob = scope.launch {
            while (isActive) {
                delay(PROGRESS_INTERVAL_MILLIS)
                if (controller?.isPlaying == true) {
                    captureProgress(immediate = false, reason = AudioProgressSaveReason.Tick)
                }
            }
        }
    }

    private fun configureProgress(
        publication: com.ermao.library.shared.modules.audio.AudioPublication,
        profile: ServerProfile,
    ) {
        activeProgressRuntime?.close()
        val identity = ReaderLocalProgressIdentity(
            namespace = publication.namespace,
            clientId = AndroidReaderDeviceIdentity(appContext).stableDeviceId(),
            bookId = publication.bookId,
            resourceId = publication.resource.resourceId,
        )
        val database = AndroidReaderProgressDatabase(appContext, identity)
        val target = ReaderProgressSyncTarget(
            namespace = publication.namespace,
            bookId = publication.bookId,
            resourceId = publication.resource.resourceId,
            sourceFormat = ReaderFormat.Audio,
        )
        val syncRuntime = ReaderProgressSyncRuntime(
            stateStore = database,
            target = target,
            server = createAndroidReaderProgressSyncPort(appContext, profile),
        )
        activeProgressRuntime = syncRuntime
        activeProgressWriter = AudioProgressWriter(
            store = syncRuntime.store,
            resourceId = publication.resource.resourceId,
            deviceId = identity.clientId,
            nowEpochMillis = System::currentTimeMillis,
        )
    }

    private fun captureProgress(
        immediate: Boolean,
        reason: AudioProgressSaveReason = if (immediate) {
            AudioProgressSaveReason.Pause
        } else {
            AudioProgressSaveReason.Tick
        },
    ) {
        val current = _snapshot.value
        if (!current.hasSession || current.phase == AndroidAudioPhase.Idle) return
        val writer = activeProgressWriter
        if (writer == null) {
            progressSink.capture(current, immediate)
            return
        }
        val assetId = current.assetId ?: return
        scope.launch {
            writer.save(
                assetId = assetId,
                chapterId = current.chapterId,
                positionMillis = current.positionMillis,
                durationMillis = current.durationMillis.takeIf { it > 0 },
                reason = reason,
            )
        }
    }

    private fun publishFromController() {
        val controller = controller ?: return
        val item = controller.currentMediaItem
        val intent = activeIntent
        if (item == null || intent == null) {
            if (_snapshot.value.phase != AndroidAudioPhase.Idle) _snapshot.value = AndroidAudioPlaybackSnapshot()
            return
        }
        val track = intent.tracks.firstOrNull { it.assetId == item.mediaId.substringAfterLast('/') }
            ?: intent.tracks.firstOrNull { item.mediaId.endsWith("/${it.assetId}") }
            ?: intent.selectedTrack
        val position = controller.currentPosition.coerceAtLeast(0)
        val duration = controller.duration.takeIf { it > 0 } ?: track.durationMillis ?: 0L
        val chapter = track.chapters.lastOrNull { it.startMillis <= position }
        val phase = when {
            lastError != null -> AndroidAudioPhase.Error
            controller.playbackState == Player.STATE_BUFFERING -> AndroidAudioPhase.Buffering
            controller.playbackState == Player.STATE_ENDED -> AndroidAudioPhase.Ended
            controller.playbackState == Player.STATE_READY && controller.isPlaying -> AndroidAudioPhase.Playing
            controller.playbackState == Player.STATE_READY -> AndroidAudioPhase.Paused
            controller.playbackState == Player.STATE_IDLE -> AndroidAudioPhase.Loading
            else -> AndroidAudioPhase.Ready
        }
        _snapshot.value = AndroidAudioPlaybackSnapshot(
            phase = phase,
            namespace = intent.namespace,
            bookId = intent.bookId,
            resourceId = intent.resourceId,
            assetId = track.assetId,
            chapterId = chapter?.id ?: intent.chapterId,
            title = intent.title,
            chapterTitle = chapter?.title,
            positionMillis = position,
            durationMillis = duration,
            bufferedPositionMillis = controller.bufferedPosition.coerceAtLeast(position),
            playbackRate = controller.playbackParameters.speed,
            error = lastError,
        )
        if (phase == AndroidAudioPhase.Playing) startProgressTicker()
        if (phase == AndroidAudioPhase.Ended) {
            captureProgress(immediate = true, reason = AudioProgressSaveReason.Completed)
        } else if (phase == AndroidAudioPhase.Paused) {
            captureProgress(immediate = true, reason = AudioProgressSaveReason.Pause)
        }
    }

    private fun currentTrackAndChapter(): Pair<Int, AndroidAudioTrack>? {
        val intent = activeIntent ?: return null
        val index = intent.tracks.indexOfFirst { it.assetId == _snapshot.value.assetId }.takeIf { it >= 0 } ?: 0
        return index to intent.tracks[index]
    }

    private fun updateChapter(chapter: AndroidAudioChapter) {
        _snapshot.value = _snapshot.value.copy(chapterId = chapter.id, chapterTitle = chapter.title)
        captureProgress(immediate = true, reason = AudioProgressSaveReason.ChapterChange)
    }

    private inner class ControllerListener : Player.Listener {
        override fun onPlaybackStateChanged(playbackState: Int) = publishFromController()

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            publishFromController()
            if (!isPlaying) captureProgress(immediate = true, reason = AudioProgressSaveReason.Pause)
        }

        override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
            val intent = activeIntent ?: return
            val assetId = mediaItem?.mediaId?.substringAfterLast('/') ?: return
            if (intent.tracks.none { it.assetId == assetId }) return
            activeIntent = intent.copy(assetId = assetId, chapterId = null, positionMillis = 0)
            publishFromController()
            captureProgress(immediate = true, reason = AudioProgressSaveReason.TrackChange)
        }

        override fun onPositionDiscontinuity(
            oldPosition: Player.PositionInfo,
            newPosition: Player.PositionInfo,
            reason: Int,
        ) {
            publishFromController()
            if (reason != Player.DISCONTINUITY_REASON_INTERNAL) {
                captureProgress(immediate = true, reason = AudioProgressSaveReason.Seek)
            }
        }

        override fun onPlaybackParametersChanged(playbackParameters: PlaybackParameters) {
            _snapshot.value = _snapshot.value.copy(playbackRate = playbackParameters.speed)
        }

        override fun onPlayerError(error: PlaybackException) {
            lastError = AndroidAudioError(
                code = stableErrorCode(error),
                recoverable = true,
            )
            publishFromController()
            captureProgress(immediate = true, reason = AudioProgressSaveReason.Pause)
        }
    }

    private fun AndroidAudioLaunchIntent.toSnapshot(phase: AndroidAudioPhase): AndroidAudioPlaybackSnapshot {
        val track = selectedTrack
        val chapter = chapterId?.let { id -> track.chapters.firstOrNull { it.id == id } }
        return AndroidAudioPlaybackSnapshot(
            phase = phase,
            namespace = namespace,
            bookId = bookId,
            resourceId = resourceId,
            assetId = track.assetId,
            chapterId = chapter?.id,
            title = title,
            chapterTitle = chapter?.title,
            positionMillis = positionMillis,
            durationMillis = track.durationMillis ?: 0,
            playbackRate = DEFAULT_PLAYBACK_RATE,
        )
    }

    private fun AndroidAudioTrack.toMediaItem(intent: AndroidAudioLaunchIntent): MediaItem =
        MediaItem.Builder()
            .setMediaId(assetId)
            .setUri(Uri.parse(sourceUri))
            .setMimeType(mimeType)
            .setCustomCacheKey(intent.namespace.key)
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(title)
                    .setArtist(intent.author)
                    // Remote cover URLs are authenticated media too. Do not let Media3's
                    // default notification bitmap loader create a second unauthenticated HTTP
                    // path; the Compose surface uses its safe fallback until a shared artwork
                    // adapter is available.
                    .setArtworkUri(intent.artworkUri?.let(::safeArtworkUri))
                    .build(),
            )
            .build()

private fun safeArtworkUri(value: String): Uri? {
    val uri = Uri.parse(value)
    return uri.takeIf { parsed ->
        parsed.scheme?.lowercase() in setOf("file", "content", "asset")
    }
}

    private data class RemoteLaunch(
        val token: Long,
        val profile: ServerProfile,
        val namespace: ReaderSyncNamespace,
        val resourceId: String,
        val chapterId: String?,
        val positionMillis: Long?,
        val titleHint: String?,
        val artworkUri: String?,
        val autoplay: Boolean,
        val bootstrapGateway: ReaderBootstrapGateway,
        val mediaTransport: AudioMediaTransport,
    )

    companion object {
        const val BACK_SKIP_MILLIS = 15_000L
        const val FORWARD_SKIP_MILLIS = 30_000L
        const val PROGRESS_INTERVAL_MILLIS = 15_000L
        const val PREVIOUS_CHAPTER_THRESHOLD_MILLIS = 3_000L
    }
}

private fun stableErrorCode(error: PlaybackException): String {
    if (error.errorCode in setOf(
            PlaybackException.ERROR_CODE_DECODER_INIT_FAILED,
            PlaybackException.ERROR_CODE_DECODER_QUERY_FAILED,
            PlaybackException.ERROR_CODE_DECODING_FAILED,
            PlaybackException.ERROR_CODE_DECODING_FORMAT_EXCEEDS_CAPABILITIES,
            PlaybackException.ERROR_CODE_DECODING_FORMAT_UNSUPPORTED,
        )
    ) return "ENGINE_CODEC_UNSUPPORTED"
    var cause: Throwable? = error
    while (cause != null) {
        val message = cause.message?.trim()
        if (message != null && message.matches(Regex("[A-Z][A-Z0-9_]{2,}"))) return message
        cause = cause.cause
    }
    return error.errorCodeName.takeUnless { it.isNullOrBlank() } ?: "AUDIO_ENGINE_ERROR"
}

private fun requestAssetId(
    publication: com.ermao.library.shared.modules.audio.AudioPublication,
    chapterId: String?,
): String? = chapterId?.let { id -> publication.chapters.firstOrNull { it.chapterId == id }?.assetId }

fun interface AndroidAudioProgressSink {
    fun capture(snapshot: AndroidAudioPlaybackSnapshot, immediate: Boolean)

    data object NoOp : AndroidAudioProgressSink {
        override fun capture(snapshot: AndroidAudioPlaybackSnapshot, immediate: Boolean) = Unit
    }
}
