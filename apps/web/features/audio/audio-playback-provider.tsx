'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { UNAUTHORIZED_EVENT } from '../../lib/auth-session';
import { activateReaderUser, currentReaderServerIdentity, getReaderRuntime } from '../../lib/reader';
import { withBasePath } from '../../lib/base-path';
import { BEFORE_PWA_UPDATE_EVENT, type BeforePwaUpdateDetail } from '../../lib/pwa/update-coordination';
import { AUDIO_DEVICE_PREFERENCES_KEY, readAudioDevicePreferences, writeAudioDevicePreferences } from '../../lib/audio-device-preferences';
import { fetchAudioBootstrap } from './api';
import {
  absolutePositionForTrack,
  audioFormatLabel,
  audioLocation,
  audioProgressPercent,
  beginAudioResourceSwitch,
  chapterAt,
  clamp,
  failAudioResourceSwitch,
  mergeAudioLoadIntent,
  nextAudioTrackForMetadataPreload,
  normalizeResumeTarget,
  pendingSeekAfterAssignment,
  targetForAbsolutePosition,
  unsupportedAudioMimeType,
  type AudioLoadIntent
} from './audio-model';
import type {
  AudioBootstrap,
  AudioLaunchSummary,
  AudioPlaybackContextValue,
  AudioPlaybackState,
  AudioTrack,
  LoadAudioResourceOptions
} from './types';

const PLAYBACK_CHANNEL = 'shuku-audio-playback';
const PLAYBACK_CLAIM_KEY = 'shuku:audio:playback-claim';
const PROGRESS_INTERVAL_MS = 15_000;

type PendingAudioResourceLoad = AudioLoadIntent & {
  resourceId: string;
  summary: AudioLaunchSummary | null;
  promise: Promise<void>;
};
type FailedAudioResourceLoad = Omit<PendingAudioResourceLoad, 'autoplay' | 'promise'>;

const initialState: AudioPlaybackState = {
  lifecycle: 'idle',
  bootstrap: null,
  resourceId: null,
  pendingResourceId: null,
  pendingSummary: null,
  loadError: null,
  bookId: null,
  trackIndex: -1,
  track: null,
  chapter: null,
  positionMs: 0,
  durationMs: 0,
  absolutePositionMs: 0,
  totalDurationMs: 0,
  playbackRate: 1,
  skipBackwardSeconds: 15,
  skipForwardSeconds: 30,
  volume: 1,
  sleepTimerEndsAt: null,
  sleepTimerMode: null,
  error: null
};

const AudioPlaybackContext = createContext<AudioPlaybackContextValue | null>(null);

function tabId() {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `audio_${suffix}`;
}

function mediaErrorMessage(audio: HTMLAudioElement, track: AudioTrack | null) {
  const format = track ? audioFormatLabel(track) : '未知格式';
  switch (audio.error?.code) {
    case MediaError.MEDIA_ERR_ABORTED:
      return '音频加载已取消，可以重试播放';
    case MediaError.MEDIA_ERR_NETWORK:
      return '音频传输中断，请检查网络或文件服务后重试';
    case MediaError.MEDIA_ERR_DECODE:
      return `浏览器无法解码这个音频（${format}），文件可能损坏或编码不受支持`;
    case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED:
      return `当前浏览器不支持这个音频来源或编码（${format}）`;
    default:
      return '音频暂时无法播放，请稍后重试';
  }
}

export function AudioPlaybackProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AudioPlaybackState>(initialState);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const stateRef = useRef(state);
  const bootstrapRef = useRef<AudioBootstrap | null>(null);
  const trackIndexRef = useRef(-1);
  const loadAbortRef = useRef<AbortController | null>(null);
  const loadSequenceRef = useRef(0);
  const pendingLoadRef = useRef<PendingAudioResourceLoad | null>(null);
  const failedLoadRef = useRef<FailedAudioResourceLoad | null>(null);
  const nextTrackPreloadAbortRef = useRef<AbortController | null>(null);
  const pendingSeekRef = useRef<number | null>(null);
  const pendingAutoplayRef = useRef(false);
  const suppressedPauseEventsRef = useRef(0);
  const lastProgressEnqueueRef = useRef(0);
  const mediaPositionUpdateRef = useRef(0);
  const playbackChannelRef = useRef<BroadcastChannel | null>(null);
  const thisTabIdRef = useRef('');
  if (!thisTabIdRef.current) thisTabIdRef.current = tabId();
  const sleepTargetChapterRef = useRef<string | null>(null);
  const runtime = getReaderRuntime();

  const updateState = useCallback((patch: Partial<AudioPlaybackState> | ((current: AudioPlaybackState) => Partial<AudioPlaybackState>)) => {
    setState((current) => {
      const next = { ...current, ...(typeof patch === 'function' ? patch(current) : patch) };
      stateRef.current = next;
      return next;
    });
  }, []);

  const claimPlayback = useCallback(() => {
    const message = { type: 'claim-playback', tabId: thisTabIdRef.current, claimedAt: Date.now() };
    playbackChannelRef.current?.postMessage(message);
    try {
      window.localStorage.setItem(PLAYBACK_CLAIM_KEY, JSON.stringify(message));
    } catch {
      // BroadcastChannel is the primary path; storage is only the fallback.
    }
  }, []);

  const persistProgress = useCallback((completed = false, flush = false) => {
    const bootstrap = bootstrapRef.current;
    const audio = audioRef.current;
    const trackIndex = trackIndexRef.current;
    const track = bootstrap?.tracks[trackIndex];
    if (!bootstrap || !track || !bootstrap.userId) return Promise.resolve();
    const positionMs = completed
      ? Math.max(0, track.durationMs)
      : clamp((audio?.currentTime ?? stateRef.current.positionMs / 1000) * 1000, 0, Math.max(track.durationMs, 0));
    const chapter = chapterAt(bootstrap.chapters, track.assetId, positionMs);
    const absolutePositionMs = completed
      ? bootstrap.totalDurationMs
      : absolutePositionForTrack(bootstrap.tracks, trackIndex, positionMs);
    const location = audioLocation(track, chapter, positionMs, bootstrap.resource.id);
    const exactLocation = {
      kind: 'audio' as const,
      assetId: location.assetId,
      ...(location.chapterId ? { chapterId: location.chapterId } : {}),
      positionMillis: Math.max(0, Math.round(location.positionMs))
    };
    lastProgressEnqueueRef.current = Date.now();
    return runtime.progress.enqueue({
      serverIdentity: currentReaderServerIdentity(),
      userId: bootstrap.userId,
      bookId: bootstrap.book.id,
      resourceId: bootstrap.resource.id,
      baseRevision: runtime.progress.getLatestServerSnapshot(bootstrap.resource.id)?.revision
        ?? bootstrap.progressRevision,
      locator: exactLocation,
      displayPercent: audioProgressPercent(absolutePositionMs, bootstrap.totalDurationMs, completed)
    }).then(() => flush ? runtime.progress.flushNow() : undefined).catch(() => undefined);
  }, [runtime.progress]);

  const playCurrentAudio = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio || !bootstrapRef.current || trackIndexRef.current < 0) return;
    claimPlayback();
    try {
      await audio.play();
      updateState({ lifecycle: 'playing', error: null });
    } catch (reason) {
      const blocked = reason instanceof DOMException && reason.name === 'NotAllowedError';
      updateState({
        lifecycle: 'paused',
        error: blocked ? '浏览器阻止了自动播放，请点按播放按钮继续' : (reason instanceof Error ? reason.message : '无法开始播放')
      });
    }
  }, [claimPlayback, updateState]);

  const attemptPendingSeek = useCallback((audio: HTMLAudioElement) => {
    const pendingPositionMs = pendingSeekRef.current;
    if (pendingPositionMs === null) return;
    let assignmentSucceeded = false;
    try {
      audio.currentTime = pendingPositionMs / 1000;
      assignmentSucceeded = true;
    } catch {
      // Keep the target for canplay. Safari can transiently reject a seek
      // during a metadata transition even after loadedmetadata.
    }
    pendingSeekRef.current = pendingSeekAfterAssignment(
      pendingPositionMs,
      audio.currentTime * 1000,
      assignmentSucceeded
    );
  }, []);

  const configureTrack = useCallback((trackIndex: number, positionMs: number, autoplay: boolean) => {
    const bootstrap = bootstrapRef.current;
    const audio = audioRef.current;
    if (!bootstrap || !audio || bootstrap.tracks.length === 0) return;
    const index = Math.max(0, Math.min(bootstrap.tracks.length - 1, trackIndex));
    const track = bootstrap.tracks[index];
    const nextPosition = clamp(positionMs, 0, Math.max(0, track.durationMs));
    const unsupportedMime = unsupportedAudioMimeType(track.mimeType, track.codec, (mime) => audio.canPlayType(mime));
    if (unsupportedMime) {
      if (!audio.paused) suppressedPauseEventsRef.current += 1;
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      trackIndexRef.current = index;
      pendingSeekRef.current = null;
      pendingAutoplayRef.current = false;
      const chapter = chapterAt(bootstrap.chapters, track.assetId, nextPosition);
      updateState({
        lifecycle: 'error',
        trackIndex: index,
        track,
        chapter,
        positionMs: nextPosition,
        durationMs: track.durationMs,
        absolutePositionMs: absolutePositionForTrack(bootstrap.tracks, index, nextPosition),
        error: `当前浏览器不支持这个音频格式（${audioFormatLabel(track)}）`
      });
      return;
    }
    if (!audio.paused) suppressedPauseEventsRef.current += 1;
    audio.pause();
    trackIndexRef.current = index;
    pendingSeekRef.current = nextPosition;
    pendingAutoplayRef.current = autoplay;
    audio.playbackRate = stateRef.current.playbackRate;
    audio.volume = stateRef.current.volume;
    audio.src = track.url;
    audio.load();
    const chapter = chapterAt(bootstrap.chapters, track.assetId, nextPosition);
    updateState({
      lifecycle: 'loading',
      trackIndex: index,
      track,
      chapter,
      positionMs: nextPosition,
      durationMs: track.durationMs,
      absolutePositionMs: absolutePositionForTrack(bootstrap.tracks, index, nextPosition),
      error: null
    });
    if (autoplay) {
      // Calling play() in the same stack as a chapter/track click preserves
      // transient user activation even while the new source is buffering.
      // The returned promise remains the authoritative success/error signal.
      pendingAutoplayRef.current = false;
      void playCurrentAudio();
    }
  }, [playCurrentAudio, updateState]);

  const loadResource = useCallback((resourceId: string, options: LoadAudioResourceOptions = {}): Promise<void> => {
    const normalizedResourceId = resourceId.trim();
    if (!normalizedResourceId) return Promise.resolve();

    const pendingLoad = pendingLoadRef.current;
    if (!options.force && pendingLoad?.resourceId === normalizedResourceId) {
      const merged = mergeAudioLoadIntent(pendingLoad, {
        autoplay: options.autoplay,
        chapterId: options.chapterId?.trim() || (options.assetId ? null : undefined),
        assetId: options.assetId?.trim() || (options.chapterId ? null : undefined)
      });
      pendingLoad.autoplay = merged.autoplay;
      pendingLoad.chapterId = merged.chapterId;
      pendingLoad.assetId = merged.assetId;
      if (options.summary) {
        pendingLoad.summary = options.summary;
        updateState({ pendingSummary: options.summary });
      }
      return pendingLoad.promise;
    }

    if (
      !options.force
      && bootstrapRef.current?.resource.id === normalizedResourceId
    ) {
      if (pendingLoadRef.current || stateRef.current.pendingResourceId) {
        loadSequenceRef.current += 1;
        loadAbortRef.current?.abort();
        loadAbortRef.current = null;
        pendingLoadRef.current = null;
      }
      failedLoadRef.current = null;
      const requestedChapter = options.chapterId
        ? bootstrapRef.current.chapters.find((chapter) => chapter.id === options.chapterId)
        : null;
      const requestedTrackIndex = requestedChapter
        ? bootstrapRef.current.tracks.findIndex((track) => track.assetId === requestedChapter.assetId)
        : options.assetId
          ? bootstrapRef.current.tracks.findIndex((track) => track.assetId === options.assetId)
          : -1;
      if (requestedTrackIndex >= 0) {
        void persistProgress(false, true);
        configureTrack(requestedTrackIndex, requestedChapter?.startMs ?? 0, Boolean(options.autoplay) || audioRef.current?.paused === false);
        return Promise.resolve();
      }
      updateState({
        pendingResourceId: null,
        pendingSummary: null,
        loadError: null,
        lifecycle: audioRef.current?.paused === false ? 'playing' : 'paused'
      });
      return options.autoplay ? playCurrentAudio() : Promise.resolve();
    }

    const requestId = loadSequenceRef.current + 1;
    loadSequenceRef.current = requestId;
    failedLoadRef.current = null;
    loadAbortRef.current?.abort();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    const request: PendingAudioResourceLoad = {
      resourceId: normalizedResourceId,
      autoplay: Boolean(options.autoplay),
      chapterId: options.chapterId?.trim() || null,
      assetId: options.assetId?.trim() || null,
      summary: options.summary ?? null,
      promise: Promise.resolve()
    };
    const operation = (async () => {
      const previousState = stateRef.current;
      const previousBootstrap = bootstrapRef.current;
      const previousTrackIndex = trackIndexRef.current;
      const previousWasPlaying = Boolean(audioRef.current && !audioRef.current.paused);
      if (previousWasPlaying && audioRef.current) {
        suppressedPauseEventsRef.current += 1;
        audioRef.current.pause();
      }
      updateState(beginAudioResourceSwitch(previousState, normalizedResourceId, request.summary));
      if (previousBootstrap) await persistProgress(false, true);
      if (controller.signal.aborted || requestId !== loadSequenceRef.current) return;
      try {
        let bootstrap = await fetchAudioBootstrap(normalizedResourceId, controller.signal);
        if (controller.signal.aborted || requestId !== loadSequenceRef.current) return;
        loadAbortRef.current = null;
        failedLoadRef.current = null;
        activateReaderUser(bootstrap.userId);
        const clientId = await runtime.storage.getClientId();
        const localExact = await runtime.storage.getExactProgress({
          serverIdentity: currentReaderServerIdentity(),
          userId: bootstrap.userId,
          clientId,
          bookId: bootstrap.book.id,
          resourceId: bootstrap.resource.id
        }).catch(() => null);
        const localAudioLocation = localExact?.locator.kind === 'audio' ? localExact.locator : null;
        if (
          localAudioLocation?.kind === 'audio'
          && (
            bootstrap.serverUpdatedAtEpochMillis === null
            || (localExact?.capturedAtEpochMillis ?? -1) >= bootstrap.serverUpdatedAtEpochMillis
          )
        ) {
          bootstrap = {
            ...bootstrap,
            resumeLocation: {
              type: 'audio',
              resourceId: bootstrap.resource.id,
              assetId: localAudioLocation.assetId,
              chapterId: localAudioLocation.chapterId ?? null,
              positionMs: localAudioLocation.positionMillis
            },
            progressPercent: localExact?.displayPercent ?? bootstrap.progressPercent
          };
        }
        bootstrapRef.current = bootstrap;
        const preferences = readAudioDevicePreferences(bootstrap.userId, bootstrap.book.id);
        const playbackRate = clamp(preferences.playbackRate ?? bootstrap.preferences.playbackRate, 0.75, 3);
        const volume = clamp(preferences.volume ?? bootstrap.preferences.volume, 0, 1);
        const requestedChapter = request.chapterId
          ? bootstrap.chapters.find((chapter) => chapter.id === request.chapterId)
          : null;
        const requestedTrackIndex = requestedChapter
          ? bootstrap.tracks.findIndex((track) => track.assetId === requestedChapter.assetId)
          : request.assetId
            ? bootstrap.tracks.findIndex((track) => track.assetId === request.assetId)
            : -1;
        const resume = requestedTrackIndex >= 0
          ? { trackIndex: requestedTrackIndex, positionMs: requestedChapter?.startMs ?? 0 }
          : normalizeResumeTarget(bootstrap);
        updateState({
          bootstrap,
          resourceId: bootstrap.resource.id,
          pendingResourceId: null,
          pendingSummary: null,
          loadError: null,
          bookId: bootstrap.book.id,
          totalDurationMs: bootstrap.totalDurationMs,
          playbackRate,
          skipBackwardSeconds: bootstrap.preferences.skipBackwardSeconds,
          skipForwardSeconds: bootstrap.preferences.skipForwardSeconds,
          volume,
          sleepTimerEndsAt: null,
          sleepTimerMode: null,
          error: null
        });
        sleepTargetChapterRef.current = null;
        configureTrack(resume.trackIndex, resume.positionMs, request.autoplay);
      } catch (reason) {
        if (controller.signal.aborted || requestId !== loadSequenceRef.current) return;
        loadAbortRef.current = null;
        const message = reason instanceof Error ? reason.message : '有声书播放器启动失败';
        bootstrapRef.current = previousBootstrap;
        trackIndexRef.current = previousTrackIndex;
        failedLoadRef.current = {
          resourceId: request.resourceId,
          chapterId: request.chapterId,
          assetId: request.assetId,
          summary: request.summary
        };
        updateState(failAudioResourceSwitch(previousState, normalizedResourceId, message, request.summary));
      }
    })();
    request.promise = operation.finally(() => {
      if (pendingLoadRef.current === request) pendingLoadRef.current = null;
    });
    pendingLoadRef.current = request;
    return request.promise;
  }, [configureTrack, persistProgress, playCurrentAudio, runtime.storage, updateState]);

  const pause = useCallback(() => {
    audioRef.current?.pause();
    updateState((current) => current.bootstrap ? { lifecycle: 'paused' } : {});
  }, [updateState]);

  const play = useCallback(async () => {
    if (stateRef.current.lifecycle === 'error' && stateRef.current.resourceId) {
      await loadResource(stateRef.current.resourceId, { autoplay: true, force: true });
      return;
    }
    await playCurrentAudio();
  }, [loadResource, playCurrentAudio]);

  const toggle = useCallback(async () => {
    if (audioRef.current && !audioRef.current.paused) pause();
    else await play();
  }, [pause, play]);

  const seekTo = useCallback((positionMs: number) => {
    const audio = audioRef.current;
    const track = bootstrapRef.current?.tracks[trackIndexRef.current];
    if (!audio || !track) return;
    const target = clamp(positionMs, 0, Math.max(track.durationMs, 0));
    pendingSeekRef.current = null;
    try {
      audio.currentTime = target / 1000;
    } catch {
      pendingSeekRef.current = target;
    }
    const bootstrap = bootstrapRef.current;
    const chapter = bootstrap ? chapterAt(bootstrap.chapters, track.assetId, target) : null;
    updateState({
      positionMs: target,
      chapter,
      absolutePositionMs: bootstrap ? absolutePositionForTrack(bootstrap.tracks, trackIndexRef.current, target) : target
    });
  }, [updateState]);

  const seekToAbsolute = useCallback((positionMs: number) => {
    const bootstrap = bootstrapRef.current;
    if (!bootstrap) return;
    const target = targetForAbsolutePosition(bootstrap.tracks, positionMs);
    if (target.trackIndex < 0) return;
    if (target.trackIndex === trackIndexRef.current) seekTo(target.positionMs);
    else {
      void persistProgress(false, true);
      configureTrack(target.trackIndex, target.positionMs, !audioRef.current?.paused);
    }
  }, [configureTrack, persistProgress, seekTo]);

  const seekBy = useCallback((seconds: number) => {
    seekToAbsolute(stateRef.current.absolutePositionMs + seconds * 1000);
  }, [seekToAbsolute]);

  const selectTrack = useCallback((trackIndex: number, autoplay = false) => {
    void persistProgress(false, true);
    configureTrack(trackIndex, 0, autoplay || !audioRef.current?.paused);
  }, [configureTrack, persistProgress]);

  const selectChapter = useCallback((chapterId: string, autoplay = false) => {
    const bootstrap = bootstrapRef.current;
    const chapter = bootstrap?.chapters.find((item) => item.id === chapterId);
    if (!bootstrap || !chapter) return;
    const trackIndex = bootstrap.tracks.findIndex((track) => track.assetId === chapter.assetId);
    if (trackIndex < 0) return;
    void persistProgress(false, true);
    if (trackIndex === trackIndexRef.current) {
      seekTo(chapter.startMs);
      if (autoplay) void playCurrentAudio();
    } else {
      configureTrack(trackIndex, chapter.startMs, autoplay || !audioRef.current?.paused);
    }
  }, [configureTrack, persistProgress, playCurrentAudio, seekTo]);

  const previousChapter = useCallback(() => {
    const bootstrap = bootstrapRef.current;
    const currentTrack = bootstrap?.tracks[trackIndexRef.current];
    if (!bootstrap || !currentTrack) return;
    const position = (audioRef.current?.currentTime ?? 0) * 1000;
    const current = chapterAt(bootstrap.chapters, currentTrack.assetId, position);
    const currentIndex = current ? bootstrap.chapters.findIndex((chapter) => chapter.id === current.id) : -1;
    if (current && position - current.startMs > 3_000) {
      seekTo(current.startMs);
      return;
    }
    if (currentIndex > 0) selectChapter(bootstrap.chapters[currentIndex - 1].id);
    else if (trackIndexRef.current > 0) selectTrack(trackIndexRef.current - 1);
    else seekTo(0);
  }, [seekTo, selectChapter, selectTrack]);

  const nextChapter = useCallback(() => {
    const bootstrap = bootstrapRef.current;
    const currentTrack = bootstrap?.tracks[trackIndexRef.current];
    if (!bootstrap || !currentTrack) return;
    const current = chapterAt(bootstrap.chapters, currentTrack.assetId, (audioRef.current?.currentTime ?? 0) * 1000);
    const currentIndex = current ? bootstrap.chapters.findIndex((chapter) => chapter.id === current.id) : -1;
    if (currentIndex >= 0 && currentIndex < bootstrap.chapters.length - 1) selectChapter(bootstrap.chapters[currentIndex + 1].id);
    else if (trackIndexRef.current < bootstrap.tracks.length - 1) selectTrack(trackIndexRef.current + 1);
  }, [selectChapter, selectTrack]);

  const setPlaybackRate = useCallback((rate: number) => {
    const normalized = clamp(rate, 0.75, 3);
    if (audioRef.current) audioRef.current.playbackRate = normalized;
    updateState({ playbackRate: normalized });
    const bootstrap = bootstrapRef.current;
    writeAudioDevicePreferences({ playbackRate: normalized, volume: stateRef.current.volume }, bootstrap?.userId, bootstrap?.book.id);
    void persistProgress();
  }, [persistProgress, updateState]);

  const setVolume = useCallback((volume: number) => {
    const normalized = clamp(volume, 0, 1);
    if (audioRef.current) audioRef.current.volume = normalized;
    updateState({ volume: normalized });
    const bootstrap = bootstrapRef.current;
    writeAudioDevicePreferences({ playbackRate: stateRef.current.playbackRate, volume: normalized }, bootstrap?.userId, bootstrap?.book.id);
  }, [updateState]);

  const setSleepTimer = useCallback((value: number | 'chapter' | null) => {
    if (value === 'chapter') {
      const current = stateRef.current.chapter;
      sleepTargetChapterRef.current = current?.id ?? `track:${stateRef.current.track?.assetId ?? ''}`;
      updateState({ sleepTimerMode: 'chapter', sleepTimerEndsAt: null });
      return;
    }
    sleepTargetChapterRef.current = null;
    if (typeof value === 'number' && value > 0) {
      updateState({ sleepTimerMode: 'timer', sleepTimerEndsAt: Date.now() + value * 60_000 });
    } else {
      updateState({ sleepTimerMode: null, sleepTimerEndsAt: null });
    }
  }, [updateState]);

  const resetPlayback = useCallback((saveProgress: boolean) => {
    if (saveProgress) void persistProgress(false, true);
    loadSequenceRef.current += 1;
    loadAbortRef.current?.abort();
    loadAbortRef.current = null;
    pendingLoadRef.current = null;
    failedLoadRef.current = null;
    nextTrackPreloadAbortRef.current?.abort();
    nextTrackPreloadAbortRef.current = null;
    const audio = audioRef.current;
    if (audio) {
      if (!audio.paused) suppressedPauseEventsRef.current += 1;
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
    }
    bootstrapRef.current = null;
    trackIndexRef.current = -1;
    pendingSeekRef.current = null;
    pendingAutoplayRef.current = false;
    sleepTargetChapterRef.current = null;
    const preferences = readAudioDevicePreferences();
    updateState({
      ...initialState,
      playbackRate: clamp(preferences.playbackRate ?? 1, 0.75, 3),
      volume: clamp(preferences.volume ?? 1, 0, 1)
    });
  }, [persistProgress, updateState]);

  const close = useCallback(() => resetPlayback(true), [resetPlayback]);

  const retry = useCallback(async () => {
    const failedLoad = failedLoadRef.current;
    const resourceId = failedLoad?.resourceId ?? stateRef.current.pendingResourceId ?? stateRef.current.resourceId;
    if (resourceId) await loadResource(resourceId, {
      force: true,
      autoplay: true,
      chapterId: failedLoad?.chapterId ?? undefined,
      assetId: failedLoad?.assetId ?? undefined,
      summary: failedLoad?.summary ?? stateRef.current.pendingSummary ?? undefined
    });
  }, [loadResource]);

  const cancelResourceSwitch = useCallback(() => {
    if (!bootstrapRef.current) return;
    loadSequenceRef.current += 1;
    loadAbortRef.current?.abort();
    loadAbortRef.current = null;
    pendingLoadRef.current = null;
    failedLoadRef.current = null;
    updateState({
      pendingResourceId: null,
      pendingSummary: null,
      loadError: null,
      lifecycle: 'paused'
    });
  }, [updateState]);

  useEffect(() => {
    const preferences = readAudioDevicePreferences();
    const playbackRate = clamp(preferences.playbackRate ?? 1, 0.75, 3);
    const volume = clamp(preferences.volume ?? 1, 0, 1);
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate;
      audioRef.current.volume = volume;
    }
    updateState({ playbackRate, volume });
  }, [updateState]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return undefined;

    const handleLoadedMetadata = () => {
      let bootstrap = bootstrapRef.current;
      let track = bootstrap?.tracks[trackIndexRef.current];
      if (!bootstrap || !track) return;
      const browserDurationMs = Number.isFinite(audio.duration) ? audio.duration * 1000 : 0;
      if (track.durationMs <= 0 && browserDurationMs > 0) {
        const tracks = bootstrap.tracks.map((item, index) => index === trackIndexRef.current ? { ...item, durationMs: browserDurationMs } : item);
        const totalDurationMs = tracks.reduce((sum, item) => sum + Math.max(0, item.durationMs), 0);
        bootstrap = { ...bootstrap, tracks, totalDurationMs };
        track = tracks[trackIndexRef.current];
        bootstrapRef.current = bootstrap;
        updateState({ bootstrap, track, totalDurationMs });
      }
      const durationMs = browserDurationMs > 0 ? browserDurationMs : track.durationMs;
      const positionMs = clamp(pendingSeekRef.current ?? audio.currentTime * 1000, 0, Math.max(durationMs, 0));
      attemptPendingSeek(audio);
      const chapter = chapterAt(bootstrap.chapters, track.assetId, positionMs);
      updateState({
        lifecycle: audio.paused ? 'paused' : 'playing',
        durationMs,
        positionMs,
        chapter,
        absolutePositionMs: absolutePositionForTrack(bootstrap.tracks, trackIndexRef.current, positionMs),
        error: null
      });
      if (pendingAutoplayRef.current) {
        pendingAutoplayRef.current = false;
        void playCurrentAudio();
      }
    };

    const handleCanPlay = () => {
      attemptPendingSeek(audio);
      updateState((current) => current.lifecycle === 'loading' ? { lifecycle: audio.paused ? 'paused' : 'playing' } : {});
    };

    const handlePlay = () => {
      claimPlayback();
      updateState({ lifecycle: 'playing', error: null });
      if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'playing';
    };

    const handlePause = () => {
      if (suppressedPauseEventsRef.current > 0) {
        suppressedPauseEventsRef.current -= 1;
        return;
      }
      if (bootstrapRef.current && !audio.ended) updateState({ lifecycle: 'paused' });
      if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'paused';
      void persistProgress(false, true);
    };

    const handleTimeUpdate = () => {
      const bootstrap = bootstrapRef.current;
      const track = bootstrap?.tracks[trackIndexRef.current];
      if (!bootstrap || !track) return;
      const positionMs = clamp(audio.currentTime * 1000, 0, Math.max(stateRef.current.durationMs || track.durationMs, 0));
      const chapter = chapterAt(bootstrap.chapters, track.assetId, positionMs);
      const absolutePositionMs = absolutePositionForTrack(bootstrap.tracks, trackIndexRef.current, positionMs);
      updateState({ positionMs, chapter, absolutePositionMs });

      if (stateRef.current.sleepTimerMode === 'chapter') {
        const target = sleepTargetChapterRef.current;
        const targetChapter = target && !target.startsWith('track:') ? bootstrap.chapters.find((item) => item.id === target) : null;
        const reachedChapterEnd = targetChapter?.assetId === track.assetId && positionMs >= Math.max(targetChapter.startMs, targetChapter.endMs - 300);
        const reachedTrackEnd = target === `track:${track.assetId}` && positionMs >= Math.max(0, stateRef.current.durationMs - 300);
        if (reachedChapterEnd || reachedTrackEnd) {
          audio.pause();
          sleepTargetChapterRef.current = null;
          updateState({ sleepTimerMode: null, sleepTimerEndsAt: null, lifecycle: 'paused' });
        }
      }

      if (Date.now() - lastProgressEnqueueRef.current >= PROGRESS_INTERVAL_MS) void persistProgress();

      if ('mediaSession' in navigator && Date.now() - mediaPositionUpdateRef.current >= 1_000) {
        mediaPositionUpdateRef.current = Date.now();
        const durationSeconds = bootstrap.totalDurationMs / 1000;
        if (durationSeconds > 0 && Number.isFinite(durationSeconds)) {
          try {
            navigator.mediaSession.setPositionState({
              duration: durationSeconds,
              playbackRate: audio.playbackRate,
              position: clamp(absolutePositionMs / 1000, 0, durationSeconds)
            });
          } catch {
            // Media Session support is partial in older Safari/Chromium builds.
          }
        }
      }
    };

    const handleSeeked = () => {
      pendingSeekRef.current = pendingSeekAfterAssignment(
        pendingSeekRef.current,
        audio.currentTime * 1000,
        true
      );
      void persistProgress(false, true);
    };
    const handleRateChange = () => updateState({ playbackRate: audio.playbackRate });
    const handleVolumeChange = () => updateState({ volume: audio.volume });
    const handleError = () => {
      if (!bootstrapRef.current) return;
      updateState({ lifecycle: 'error', error: mediaErrorMessage(audio, stateRef.current.track) });
    };
    const handleEnded = () => {
      const bootstrap = bootstrapRef.current;
      if (!bootstrap) return;
      if (stateRef.current.sleepTimerMode === 'chapter') {
        sleepTargetChapterRef.current = null;
        updateState({ sleepTimerMode: null, sleepTimerEndsAt: null, lifecycle: 'paused' });
        void persistProgress(false, true);
        return;
      }
      if (trackIndexRef.current < bootstrap.tracks.length - 1) {
        void persistProgress(false, true);
        configureTrack(trackIndexRef.current + 1, 0, true);
      } else {
        const lastTrack = bootstrap.tracks[bootstrap.tracks.length - 1];
        updateState({
          lifecycle: 'paused',
          positionMs: lastTrack.durationMs,
          durationMs: lastTrack.durationMs,
          absolutePositionMs: bootstrap.totalDurationMs
        });
        void persistProgress(true, true);
      }
    };

    audio.addEventListener('loadedmetadata', handleLoadedMetadata);
    audio.addEventListener('canplay', handleCanPlay);
    audio.addEventListener('play', handlePlay);
    audio.addEventListener('pause', handlePause);
    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('seeked', handleSeeked);
    audio.addEventListener('ratechange', handleRateChange);
    audio.addEventListener('volumechange', handleVolumeChange);
    audio.addEventListener('error', handleError);
    audio.addEventListener('ended', handleEnded);
    return () => {
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
      audio.removeEventListener('canplay', handleCanPlay);
      audio.removeEventListener('play', handlePlay);
      audio.removeEventListener('pause', handlePause);
      audio.removeEventListener('timeupdate', handleTimeUpdate);
      audio.removeEventListener('seeked', handleSeeked);
      audio.removeEventListener('ratechange', handleRateChange);
      audio.removeEventListener('volumechange', handleVolumeChange);
      audio.removeEventListener('error', handleError);
      audio.removeEventListener('ended', handleEnded);
    };
  }, [attemptPendingSeek, claimPlayback, configureTrack, persistProgress, playCurrentAudio, updateState]);

  useEffect(() => {
    nextTrackPreloadAbortRef.current?.abort();
    nextTrackPreloadAbortRef.current = null;
    const bootstrap = bootstrapRef.current;
    const audio = audioRef.current;
    const nextTrack = bootstrap ? nextAudioTrackForMetadataPreload(bootstrap.tracks, state.trackIndex) : null;
    if (!nextTrack || !audio || unsupportedAudioMimeType(nextTrack.mimeType, nextTrack.codec, (mime) => audio.canPlayType(mime))) return undefined;
    const controller = new AbortController();
    nextTrackPreloadAbortRef.current = controller;
    // A HEAD request primes authenticated file metadata without downloading
    // the next (potentially multi-gigabyte) audio payload or creating a second
    // media element.
    void fetch(nextTrack.url, {
      method: 'HEAD',
      credentials: 'same-origin',
      signal: controller.signal
    }).catch(() => undefined);
    return () => {
      controller.abort();
      if (nextTrackPreloadAbortRef.current === controller) nextTrackPreloadAbortRef.current = null;
    };
  }, [state.bootstrap?.resource.id, state.trackIndex]);

  useEffect(() => {
    if (state.sleepTimerMode !== 'timer' || !state.sleepTimerEndsAt) return undefined;
    const delay = Math.max(0, state.sleepTimerEndsAt - Date.now());
    const timer = window.setTimeout(() => {
      audioRef.current?.pause();
      updateState({ sleepTimerMode: null, sleepTimerEndsAt: null, lifecycle: 'paused' });
    }, Math.min(delay, 2_147_000_000));
    return () => window.clearTimeout(timer);
  }, [state.sleepTimerEndsAt, state.sleepTimerMode, updateState]);

  useEffect(() => {
    const receiveClaim = (message: unknown) => {
      const value = message && typeof message === 'object' ? message as { type?: string; tabId?: string } : {};
      if (value.type !== 'claim-playback' || !value.tabId || value.tabId === thisTabIdRef.current) return;
      const audio = audioRef.current;
      if (audio && !audio.paused) {
        audio.pause();
        void persistProgress(false, true);
      }
    };
    const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel(PLAYBACK_CHANNEL) : null;
    playbackChannelRef.current = channel;
    const onMessage = (event: MessageEvent) => receiveClaim(event.data);
    const onStorage = (event: StorageEvent) => {
      if (event.key !== PLAYBACK_CLAIM_KEY || !event.newValue) return;
      try { receiveClaim(JSON.parse(event.newValue)); } catch { /* ignore malformed legacy values */ }
    };
    channel?.addEventListener('message', onMessage);
    window.addEventListener('storage', onStorage);
    return () => {
      channel?.removeEventListener('message', onMessage);
      channel?.close();
      if (playbackChannelRef.current === channel) playbackChannelRef.current = null;
      window.removeEventListener('storage', onStorage);
    };
  }, [persistProgress]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'hidden') void persistProgress(false, true);
    };
    const handlePageHide = () => void persistProgress(false, true);
    const handleUnauthorized = () => {
      resetPlayback(false);
    };
    const handlePrivateDataClearing = () => {
      try {
        const keys: string[] = [];
        for (let index = 0; index < window.localStorage.length; index += 1) {
          const key = window.localStorage.key(index);
          if (key && (key === AUDIO_DEVICE_PREFERENCES_KEY || key.startsWith(`${AUDIO_DEVICE_PREFERENCES_KEY}:`))) keys.push(key);
        }
        keys.forEach((key) => window.localStorage.removeItem(key));
        window.localStorage.removeItem(PLAYBACK_CLAIM_KEY);
      } catch {
        // Storage may be unavailable while signing out in private mode.
      }
      resetPlayback(false);
    };
    const handleBeforePwaUpdate = (event: Event) => {
      const detail = (event as CustomEvent<BeforePwaUpdateDetail>).detail;
      if (!detail?.waitUntil) return;
      detail.waitUntil((async () => {
        const audio = audioRef.current;
        if (pendingLoadRef.current) pendingLoadRef.current.autoplay = false;
        pendingAutoplayRef.current = false;
        if (audio && !audio.paused) {
          suppressedPauseEventsRef.current += 1;
          audio.pause();
        }
        updateState((current) => current.bootstrap ? { lifecycle: 'paused' } : {});
        await persistProgress(false, true);
      })());
    };
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('pagehide', handlePageHide);
    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    window.addEventListener('shuku:private-data-clearing', handlePrivateDataClearing);
    window.addEventListener(BEFORE_PWA_UPDATE_EVENT, handleBeforePwaUpdate);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('pagehide', handlePageHide);
      window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
      window.removeEventListener('shuku:private-data-clearing', handlePrivateDataClearing);
      window.removeEventListener(BEFORE_PWA_UPDATE_EVENT, handleBeforePwaUpdate);
    };
  }, [persistProgress, resetPlayback, updateState]);

  useEffect(() => {
    if (!('mediaSession' in navigator)) return undefined;
    const mediaSession = navigator.mediaSession;
    const handlers: Array<[MediaSessionAction, MediaSessionActionHandler | null]> = [
      ['play', () => { void play(); }],
      ['pause', pause],
      ['stop', pause],
      ['seekbackward', (details) => seekBy(-(details.seekOffset ?? stateRef.current.skipBackwardSeconds))],
      ['seekforward', (details) => seekBy(details.seekOffset ?? stateRef.current.skipForwardSeconds)],
      ['seekto', (details) => {
        if (typeof details.seekTime === 'number') seekToAbsolute(details.seekTime * 1000);
      }],
      ['previoustrack', previousChapter],
      ['nexttrack', nextChapter]
    ];
    handlers.forEach(([action, handler]) => {
      try { mediaSession.setActionHandler(action, handler); } catch { /* optional action */ }
    });
    return () => handlers.forEach(([action]) => {
      try { mediaSession.setActionHandler(action, null); } catch { /* optional action */ }
    });
  }, [nextChapter, pause, play, previousChapter, seekBy, seekToAbsolute]);

  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    const bootstrap = state.bootstrap;
    if (!bootstrap || !state.track) {
      navigator.mediaSession.metadata = null;
      return;
    }
    const cover = bootstrap.book.coverUrl
      ? withBasePath(bootstrap.book.coverUrl)
      : withBasePath(`/api/books/${encodeURIComponent(bootstrap.book.id)}/cover?size=large`);
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: state.chapter?.title ?? state.track.title,
        artist: bootstrap.book.author ?? '',
        album: bootstrap.book.title,
        artwork: [{ src: cover }]
      });
    } catch {
      // Metadata is enhancement-only; native audio remains fully usable.
    }
  }, [state.bootstrap, state.chapter?.id, state.chapter?.title, state.track]);

  const value = useMemo<AudioPlaybackContextValue>(() => ({
    ...state,
    loadResource,
    retry,
    cancelResourceSwitch,
    play,
    pause,
    toggle,
    close,
    seekBy,
    seekTo,
    seekToAbsolute,
    previousChapter,
    nextChapter,
    selectChapter,
    selectTrack,
    setPlaybackRate,
    setVolume,
    setSleepTimer
  }), [
    cancelResourceSwitch,
    close,
    loadResource,
    nextChapter,
    pause,
    play,
    previousChapter,
    retry,
    seekBy,
    seekTo,
    seekToAbsolute,
    selectChapter,
    selectTrack,
    setPlaybackRate,
    setSleepTimer,
    setVolume,
    state,
    toggle
  ]);

  return (
    <AudioPlaybackContext.Provider value={value}>
      {children}
      <audio ref={audioRef} preload="metadata" className="hidden" aria-hidden="true" />
    </AudioPlaybackContext.Provider>
  );
}

export function useAudioPlayback() {
  const value = useContext(AudioPlaybackContext);
  if (!value) throw new Error('useAudioPlayback 必须在 AudioPlaybackProvider 内使用');
  return value;
}
