package com.ermao.library.features.audio.application

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import androidx.annotation.OptIn as AndroidXOptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
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
class AndroidAudioPlaybackRuntime private constructor(
    private val appContext: Context?,
    private val transportRegistry: AndroidAudioTransportRegistry?,
    private val progressSink: AndroidAudioProgressSink,
    private val scope: CoroutineScope,
    initialController: AndroidAudioMediaController?,
    private val mediaItemsForLaunch: (AndroidAudioLaunchIntent) -> List<MediaItem>,
) : Closeable {
    constructor(
        context: Context,
        transportRegistry: AndroidAudioTransportRegistry? = null,
        progressSink: AndroidAudioProgressSink = AndroidAudioProgressSink.NoOp,
    ) : this(
        appContext = context.applicationContext,
        transportRegistry = transportRegistry,
        progressSink = progressSink,
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate),
        initialController = null,
        mediaItemsForLaunch = ::buildAudioMediaItems,
    )

    /** Test-only construction path: use the same runtime transaction with a fake engine port. */
    internal constructor(
        controller: AndroidAudioMediaController,
        scope: CoroutineScope,
        progressSink: AndroidAudioProgressSink = AndroidAudioProgressSink.NoOp,
    ) : this(
        appContext = null,
        transportRegistry = null,
        progressSink = progressSink,
        scope = scope,
        initialController = controller,
        mediaItemsForLaunch = { intent ->
            intent.tracks.map { track -> MediaItem.Builder().setMediaId(track.assetId).build() }
        },
    )

    private val mainExecutor: Executor? = appContext?.let(ContextCompat::getMainExecutor)
    private val generation = AtomicLong(0)
    private val sharedStateMachine = AudioPlaybackStateMachine()
    private val _snapshot = MutableStateFlow(AndroidAudioPlaybackSnapshot())

    private var controller: AndroidAudioMediaController? = null
    private var controllerFuture: com.google.common.util.concurrent.ListenableFuture<MediaController>? = null
    private var pendingLaunch: AndroidAudioLaunchIntent? = null
    private var activeIntent: AndroidAudioLaunchIntent? = null
    private var positionRefreshJob: Job? = null
    private var progressJob: Job? = null
    private var lastError: AndroidAudioError? = null
    private var remoteLaunch: RemoteLaunch? = null
    private var activePublication: com.ermao.library.shared.modules.audio.AudioPublication? = null
    private var sharedSessionId: Long? = null
    private var activeProgressRuntime: ReaderProgressSyncRuntime? = null
    private var activeProgressWriter: AudioProgressWriter? = null
    private var seekRequestId = 0L
    private var activeSeek: ActiveSeek? = null
    private var seekTimeoutJob: Job? = null
    private var progressOperationJob: Job? = null
    private var transportExpectation: Boolean? = null

    val snapshot: StateFlow<AndroidAudioPlaybackSnapshot> = _snapshot.asStateFlow()

    init {
        if (initialController != null) {
            controller = initialController
            initialController.addListener(ControllerListener())
            publishFromController()
        } else {
            connect()
        }
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
        cancelSeekTimeout()
        activeSeek = null
        transportExpectation = null
        stopPlaybackTickers()
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
        artworkApiPath: String? = null,
        positionMillis: Long = 0,
    ) {
        requireNotNull(appContext) { "AUDIO_ANDROID_CONTEXT_REQUIRED" }
        require(localFile.isFile && localFile.length() > 0) { "AUDIO_LOCAL_ARTIFACT_UNAVAILABLE" }
        launch(
            AndroidAudioLaunchIntent(
                namespace = namespace,
                bookId = bookId,
                resourceId = resourceId,
                title = title,
                author = author,
                artworkUri = artworkApiPath,
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
                artworkApiPath = artworkUri,
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
                        artworkUri = artworkUri ?: publication.coverApiPath,
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
                            artworkApiPath = artworkUri,
                            error = AndroidAudioError(result.code, result.recoverable),
                        )
                    }
                }
            }
        }
    }

    fun play() {
        if (activeSeek != null) return
        requestTransport(playing = true)
    }

    fun pause() {
        if (activeSeek != null) return
        requestTransport(playing = false)
    }

    /** App-owned stop: save first, then release the current queue and clear the mini player. */
    fun stop() {
        activeSeek = null
        cancelSeekTimeout()
        transportExpectation = null
        captureProgress(immediate = true, reason = AudioProgressSaveReason.Stop)
        pendingLaunch = null
        activeIntent = null
        remoteLaunch = null
        stopPlaybackTickers()
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

    fun beginScrubbing() {
        val controller = controller ?: return
        if (activeSeek != null || !snapshot.value.hasSession) return
        val track = currentTrackAndChapter()?.second ?: return
        val resumeAfterSeek = controller.isPlaying
        transportExpectation = null
        seekRequestId += 1
        activeSeek = ActiveSeek(
            requestId = seekRequestId,
            resumeAfterSeek = resumeAfterSeek,
            mediaItemIndex = controller.currentMediaItemIndex.coerceAtLeast(0),
            assetId = track.assetId,
            chapterId = snapshot.value.chapterId,
            targetPositionMillis = snapshot.value.positionMillis,
            waitingForEngine = false,
            pauseIssued = resumeAfterSeek,
        )
        stopPlaybackTickers()
        _snapshot.value = _snapshot.value.copy(phase = AndroidAudioPhase.Paused)
        if (resumeAfterSeek) requestTransport(playing = false)
    }

    fun updateScrubbing(positionMillis: Long) {
        val pending = activeSeek?.takeIf { !it.waitingForEngine } ?: return
        val duration = snapshot.value.durationMillis.takeIf { it > 0 }
        val target = clampSeekPosition(positionMillis, duration)
        val track = activeIntent?.tracks?.getOrNull(pending.mediaItemIndex)
        val chapter = track?.chapters?.lastOrNull { it.startMillis <= target }
        activeSeek = pending.copy(
            targetPositionMillis = target,
            chapterId = chapter?.id,
        )
        _snapshot.value = _snapshot.value.copy(
            positionMillis = target,
            chapterId = chapter?.id ?: _snapshot.value.chapterId,
            chapterTitle = chapter?.title ?: _snapshot.value.chapterTitle,
        )
    }

    fun finishScrubbing() {
        val pending = activeSeek?.takeIf { !it.waitingForEngine } ?: return
        beginEngineSeek(pending)
    }

    fun cancelScrubbing() {
        val pending = activeSeek?.takeIf { !it.waitingForEngine } ?: return
        activeSeek = null
        publishFromController()
        if (pending.resumeAfterSeek) requestTransport(playing = true)
    }

    fun seekTo(positionMillis: Long) {
        val controller = controller ?: return
        if (activeSeek != null) return
        val currentIndex = controller.currentMediaItemIndex.coerceAtLeast(0)
        val track = activeIntent?.tracks?.getOrNull(currentIndex) ?: return
        val duration = controller.duration.takeIf { it > 0 } ?: track.durationMillis
        val target = clampSeekPosition(positionMillis, duration)
        val chapter = track.chapters.lastOrNull { it.startMillis <= target }
        seekRequestId += 1
        beginEngineSeek(ActiveSeek(
            requestId = seekRequestId,
            resumeAfterSeek = controller.isPlaying,
            mediaItemIndex = currentIndex,
            assetId = track.assetId,
            chapterId = chapter?.id,
            targetPositionMillis = target,
            waitingForEngine = false,
        ))
    }

    fun skipBack() = seekTo((controller?.currentPosition ?: snapshot.value.positionMillis) - BACK_SKIP_MILLIS)

    fun skipForward() = seekTo((controller?.currentPosition ?: snapshot.value.positionMillis) + FORWARD_SKIP_MILLIS)

    fun previous() {
        val current = currentTrackAndChapter() ?: return
        val chapters = current.second.chapters
        val chapterIndex = chapters.indexOfFirst { it.id == snapshot.value.chapterId }
        if (chapterIndex > 0) {
            seekTo(chapters[chapterIndex - 1].startMillis)
        } else if (snapshot.value.positionMillis > PREVIOUS_CHAPTER_THRESHOLD_MILLIS && chapterIndex >= 0) {
            seekTo(chapters[chapterIndex].startMillis)
        } else if (controller?.hasPreviousMediaItem() == true) {
            selectTrackAt((controller?.currentMediaItemIndex ?: 0) - 1)
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
        } else if (controller?.hasNextMediaItem() == true) {
            selectTrackAt((controller?.currentMediaItemIndex ?: -1) + 1)
        } else {
            controller?.seekTo(0)
            requestTransport(playing = false)
        }
    }

    fun selectChapter(chapterId: String) {
        val intent = activeIntent ?: return
        val track = intent.tracks.firstOrNull { candidate ->
            candidate.chapters.any { it.id == chapterId }
        } ?: return
        selectChapter(track.assetId, chapterId)
    }

    fun selectChapter(assetId: String, chapterId: String) {
        val intent = activeIntent ?: return
        val trackIndex = intent.tracks.indexOfFirst { it.assetId == assetId }
        if (trackIndex < 0) return
        val track = intent.tracks[trackIndex]
        val chapter = track.chapters.firstOrNull { it.id == chapterId } ?: return
        val controller = controller ?: return
        if (activeSeek != null) return
        seekRequestId += 1
        beginEngineSeek(ActiveSeek(
            requestId = seekRequestId,
            resumeAfterSeek = controller.isPlaying,
            mediaItemIndex = trackIndex,
            assetId = assetId,
            chapterId = chapterId,
            targetPositionMillis = chapter.startMillis,
            waitingForEngine = false,
        ))
    }

    fun selectAsset(assetId: String) {
        val intent = activeIntent ?: return
        val trackIndex = intent.tracks.indexOfFirst { it.assetId == assetId }
        if (trackIndex < 0) return
        val controller = controller ?: return
        if (activeSeek != null) return
        seekRequestId += 1
        beginEngineSeek(ActiveSeek(
            requestId = seekRequestId,
            resumeAfterSeek = controller.isPlaying,
            mediaItemIndex = trackIndex,
            assetId = assetId,
            chapterId = null,
            targetPositionMillis = 0,
            waitingForEngine = false,
        ))
    }

    fun setPlaybackRate(rate: Float) {
        val selected = SUPPORTED_PLAYBACK_RATES.firstOrNull { it == rate } ?: return
        controller?.setPlaybackRate(selected)
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
        cancelSeekTimeout()
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
        val appContext = requireNotNull(appContext) { "AUDIO_ANDROID_CONTEXT_REQUIRED" }
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
                controller = Media3AudioMediaController(connected)
                controller?.addListener(ControllerListener())
                pendingLaunch?.let { launch(it) }
                publishFromController()
            },
            requireNotNull(mainExecutor) { "AUDIO_ANDROID_MAIN_EXECUTOR_REQUIRED" },
        )
    }

    private fun applyLaunch(
        controller: AndroidAudioMediaController,
        intent: AndroidAudioLaunchIntent,
        launchGeneration: Long,
    ) {
        if (generation.get() != launchGeneration || activeIntent !== intent) return
        val mediaItems = mediaItemsForLaunch(intent)
        val selectedIndex = intent.tracks.indexOfFirst { it.assetId == intent.assetId }.takeIf { it >= 0 } ?: 0
        controller.setMediaItems(mediaItems, selectedIndex, intent.positionMillis)
        controller.setPlaybackRate(DEFAULT_PLAYBACK_RATE)
        controller.prepare()
        requestTransport(playing = intent.autoplay, controller = controller)
        pendingLaunch = null
        publishFromController()
        if (intent.autoplay) startPlaybackTickers()
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

    private fun startPlaybackTickers() {
        // Media3 exposes currentPosition as a value, not an observable stream. Refresh the UI
        // snapshot independently from the much slower durable progress-save cadence.
        if (positionRefreshJob?.isActive != true) {
            positionRefreshJob = scope.launch {
                while (isActive) {
                    delay(POSITION_REFRESH_INTERVAL_MILLIS)
                    if (controller?.isPlaying == true) publishFromController()
                }
            }
        }
        if (progressJob?.isActive == true) return
        progressJob = scope.launch {
            while (isActive) {
                delay(PROGRESS_INTERVAL_MILLIS)
                if (controller?.isPlaying == true) {
                    publishFromController()
                    captureProgress(immediate = false, reason = AudioProgressSaveReason.Tick)
                }
            }
        }
    }

    private fun stopPlaybackTickers() {
        positionRefreshJob?.cancel()
        positionRefreshJob = null
        progressJob?.cancel()
        progressJob = null
    }

    private fun configureProgress(
        publication: com.ermao.library.shared.modules.audio.AudioPublication,
        profile: ServerProfile,
    ) {
        val appContext = requireNotNull(appContext) { "AUDIO_ANDROID_CONTEXT_REQUIRED" }
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
        val previous = progressOperationJob
        progressOperationJob = scope.launch {
            previous?.join()
            writer.save(
                assetId = assetId,
                chapterId = current.chapterId,
                positionMillis = current.positionMillis,
                durationMillis = current.durationMillis.takeIf { it > 0 },
                reason = reason,
            )
        }
    }

    private fun beginEngineSeek(request: ActiveSeek) {
        val controller = controller ?: return
        val intent = activeIntent ?: return
        val track = intent.tracks.getOrNull(request.mediaItemIndex) ?: return
        val duration = track.durationMillis
        val target = clampSeekPosition(request.targetPositionMillis, duration)
        val chapter = request.chapterId?.let { chapterId ->
            track.chapters.firstOrNull { it.id == chapterId }
        } ?: track.chapters.lastOrNull { it.startMillis <= target }
        val pending = request.copy(
            assetId = track.assetId,
            chapterId = chapter?.id,
            targetPositionMillis = target,
            waitingForEngine = true,
            discontinuityObserved = false,
            pauseIssued = request.pauseIssued || controller.isPlaying,
        )
        activeSeek = pending
        stopPlaybackTickers()
        lastError = null
        _snapshot.value = _snapshot.value.copy(
            phase = AndroidAudioPhase.Loading,
            assetId = track.assetId,
            chapterId = chapter?.id,
            chapterTitle = chapter?.title,
            positionMillis = target,
            durationMillis = duration ?: _snapshot.value.durationMillis,
            error = null,
        )
        if (!request.pauseIssued && controller.isPlaying) {
            requestTransport(playing = false, controller = controller)
        }
        if (activeSeek?.requestId != pending.requestId) return
        startSeekTimeout(pending.requestId)
        controller.seekTo(pending.mediaItemIndex, target)
    }

    private fun maybeCompleteEngineSeek(): Boolean {
        val pending = activeSeek?.takeIf { it.waitingForEngine && it.discontinuityObserved }
            ?: return false
        val controller = controller ?: return false
        if (controller.playbackState != Player.STATE_READY) return false
        val intent = activeIntent ?: return false
        activeIntent = intent.copy(
            assetId = pending.assetId,
            chapterId = pending.chapterId,
            positionMillis = pending.targetPositionMillis,
        )
        cancelSeekTimeout()
        activeSeek = null
        publishFromController(captureLifecycleProgress = false)
        captureProgress(immediate = true, reason = AudioProgressSaveReason.Seek)
        if (pending.resumeAfterSeek) requestTransport(playing = true, controller = controller)
        return true
    }

    private fun startSeekTimeout(requestId: Long) {
        cancelSeekTimeout()
        seekTimeoutJob = scope.launch {
            delay(SEEK_TIMEOUT_MILLIS)
            val pending = activeSeek
            if (pending?.waitingForEngine != true || pending.requestId != requestId) return@launch
            seekTimeoutJob = null
            activeSeek = null
            transportExpectation = null
            lastError = AndroidAudioError(
                code = "AUDIO_SEEK_TIMEOUT",
                recoverable = true,
            )
            publishFromController(captureLifecycleProgress = false)
        }
    }

    private fun cancelSeekTimeout() {
        seekTimeoutJob?.cancel()
        seekTimeoutJob = null
    }

    private fun requestTransport(
        playing: Boolean,
        controller: AndroidAudioMediaController? = this.controller,
    ) {
        val activeController = controller ?: return
        // MediaController commands and Player.Listener facts are asynchronous. Remember only a
        // state-changing command so a delayed fact from the superseded command cannot reverse it.
        transportExpectation = playing.takeIf { activeController.isPlaying != playing }
        if (playing) activeController.play() else activeController.pause()
    }

    private fun publishFromController(captureLifecycleProgress: Boolean = true) {
        val controller = controller ?: return
        if (activeSeek != null) return
        val currentMediaItemId = controller.currentMediaItemId
        val intent = activeIntent
        if (currentMediaItemId == null || intent == null) {
            if (_snapshot.value.phase != AndroidAudioPhase.Idle) _snapshot.value = AndroidAudioPlaybackSnapshot()
            return
        }
        val track = intent.tracks.firstOrNull { it.assetId == currentMediaItemId.substringAfterLast('/') }
            ?: intent.tracks.firstOrNull { currentMediaItemId.endsWith("/${it.assetId}") }
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
            author = intent.author,
            artworkApiPath = intent.artworkUri,
            chapterTitle = chapter?.title,
            positionMillis = position,
            durationMillis = duration,
            bufferedPositionMillis = controller.bufferedPosition.coerceAtLeast(position),
            playbackRate = controller.playbackRate,
            error = lastError,
        )
        if (phase == AndroidAudioPhase.Playing) {
            startPlaybackTickers()
        } else {
            stopPlaybackTickers()
        }
        if (captureLifecycleProgress && phase == AndroidAudioPhase.Ended) {
            captureProgress(immediate = true, reason = AudioProgressSaveReason.Completed)
        } else if (captureLifecycleProgress && phase == AndroidAudioPhase.Paused) {
            captureProgress(immediate = true, reason = AudioProgressSaveReason.Pause)
        }
    }

    private fun currentTrackAndChapter(): Pair<Int, AndroidAudioTrack>? {
        val intent = activeIntent ?: return null
        val index = intent.tracks.indexOfFirst { it.assetId == _snapshot.value.assetId }.takeIf { it >= 0 } ?: 0
        return index to intent.tracks[index]
    }

    private fun selectTrackAt(trackIndex: Int) {
        val controller = controller ?: return
        val track = activeIntent?.tracks?.getOrNull(trackIndex) ?: return
        if (activeSeek != null) return
        seekRequestId += 1
        beginEngineSeek(ActiveSeek(
            requestId = seekRequestId,
            resumeAfterSeek = controller.isPlaying,
            mediaItemIndex = trackIndex,
            assetId = track.assetId,
            chapterId = track.chapters.firstOrNull()?.id,
            targetPositionMillis = 0,
            waitingForEngine = false,
        ))
    }

    private inner class ControllerListener : AndroidAudioMediaController.Listener {
        override fun onPlaybackStateChanged(playbackState: Int) {
            if (!maybeCompleteEngineSeek()) publishFromController()
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            val controller = controller ?: return
            // Media3 can deliver an older callback after a newer command has already changed the
            // controller's public fact. Such a callback must never become the UI state.
            if (controller.isPlaying != isPlaying) return
            transportExpectation?.let { expected ->
                if (expected != isPlaying) return
                transportExpectation = null
            }
            if (activeSeek != null) return
            publishFromController(captureLifecycleProgress = pendingLaunch == null)
        }

        override fun onMediaItemTransition(mediaItemId: String?, reason: Int) {
            if (activeSeek != null) return
            val intent = activeIntent ?: return
            val assetId = mediaItemId?.substringAfterLast('/') ?: return
            if (intent.tracks.none { it.assetId == assetId }) return
            activeIntent = intent.copy(assetId = assetId, chapterId = null, positionMillis = 0)
            publishFromController(captureLifecycleProgress = false)
            captureProgress(immediate = true, reason = AudioProgressSaveReason.TrackChange)
        }

        override fun onPositionDiscontinuity(
            newPosition: AndroidAudioMediaController.Position,
            reason: Int,
        ) {
            val pending = activeSeek
            if (pending != null) {
                if (pending.waitingForEngine) {
                    val currentMediaItemId = controller?.currentMediaItemId
                    val matchesTarget = newPosition.mediaItemIndex == pending.mediaItemIndex &&
                        controller?.currentMediaItemIndex == pending.mediaItemIndex &&
                        (currentMediaItemId == pending.assetId ||
                            currentMediaItemId?.endsWith("/${pending.assetId}") == true) &&
                        absoluteDifference(newPosition.positionMillis, pending.targetPositionMillis) <=
                        SEEK_POSITION_ACCEPTANCE_MILLIS &&
                        controller?.currentPosition?.let { currentPosition ->
                            absoluteDifference(currentPosition, pending.targetPositionMillis) <=
                                SEEK_POSITION_ACCEPTANCE_MILLIS
                        } == true
                    if (reason == Player.DISCONTINUITY_REASON_SEEK && matchesTarget) {
                        activeSeek = pending.copy(discontinuityObserved = true)
                        maybeCompleteEngineSeek()
                    }
                }
                // While the finger is down or the seek is awaiting confirmation, every engine
                // discontinuity belongs to the old timeline unless it completes the transaction.
                // Never publish or persist the slider's presentation-only target here.
                return
            }
            publishFromController()
            if (reason != Player.DISCONTINUITY_REASON_INTERNAL) {
                captureProgress(immediate = true, reason = AudioProgressSaveReason.Seek)
            }
        }

        override fun onPlaybackRateChanged(rate: Float) {
            _snapshot.value = _snapshot.value.copy(playbackRate = rate)
        }

        override fun onPlayerError(code: String) {
            val wasSeeking = activeSeek != null
            val error = AndroidAudioError(
                code = code,
                recoverable = true,
            )
            cancelSeekTimeout()
            activeSeek = null
            transportExpectation = null
            lastError = error
            publishFromController(captureLifecycleProgress = false)
            if (!wasSeeking) captureProgress(immediate = true, reason = AudioProgressSaveReason.Pause)
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
            author = author,
            artworkApiPath = artworkUri,
            chapterTitle = chapter?.title,
            positionMillis = positionMillis,
            durationMillis = track.durationMillis ?: 0,
            playbackRate = DEFAULT_PLAYBACK_RATE,
        )
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

    private data class ActiveSeek(
        val requestId: Long,
        val resumeAfterSeek: Boolean,
        val mediaItemIndex: Int,
        val assetId: String,
        val chapterId: String?,
        val targetPositionMillis: Long,
        val waitingForEngine: Boolean,
        val discontinuityObserved: Boolean = false,
        val pauseIssued: Boolean = false,
    )

    companion object {
        const val BACK_SKIP_MILLIS = 15_000L
        const val FORWARD_SKIP_MILLIS = 30_000L
        const val POSITION_REFRESH_INTERVAL_MILLIS = 500L
        const val PROGRESS_INTERVAL_MILLIS = 15_000L
        const val PREVIOUS_CHAPTER_THRESHOLD_MILLIS = 3_000L
        const val SEEK_POSITION_ACCEPTANCE_MILLIS = 5_000L
        const val SEEK_TIMEOUT_MILLIS = 15_000L
    }
}

@AndroidXOptIn(markerClass = [UnstableApi::class])
private fun buildAudioMediaItems(intent: AndroidAudioLaunchIntent): List<MediaItem> =
    intent.tracks.map { track ->
        MediaItem.Builder()
            .setMediaId(track.assetId)
            .setUri(track.sourceUri.toUri())
            .setMimeType(track.mimeType)
            .setCustomCacheKey(intent.namespace.key)
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(track.title)
                    .setArtist(intent.author)
                    // Remote cover URLs are authenticated media too. Do not let Media3's
                    // default notification bitmap loader create a second unauthenticated HTTP
                    // path; the Compose surface uses its safe fallback until a shared artwork
                    // adapter is available.
                    .setArtworkUri(intent.artworkUri?.let(::safeArtworkUri))
                    .build(),
            )
            .build()
    }

private fun safeArtworkUri(value: String): Uri? {
    val uri = value.toUri()
    return uri.takeIf { parsed ->
        parsed.scheme?.lowercase() in setOf("file", "content", "asset")
    }
}

internal fun stableErrorCode(error: PlaybackException): String {
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

private fun clampSeekPosition(positionMillis: Long, durationMillis: Long?): Long =
    positionMillis.coerceAtLeast(0).let { position ->
        durationMillis?.takeIf { it > 0 }?.let(position::coerceAtMost) ?: position
    }

private fun absoluteDifference(left: Long, right: Long): Long =
    if (left >= right) left - right else right - left

fun interface AndroidAudioProgressSink {
    fun capture(snapshot: AndroidAudioPlaybackSnapshot, immediate: Boolean)

    data object NoOp : AndroidAudioProgressSink {
        override fun capture(snapshot: AndroidAudioPlaybackSnapshot, immediate: Boolean) = Unit
    }
}
