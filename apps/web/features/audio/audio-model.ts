import type { AudioBootstrap, AudioChapter, AudioLaunchSummary, AudioLocation, AudioPlaybackState, AudioTrack } from './types';

export type AudioLoadIntent = {
  autoplay: boolean;
  chapterId: string | null;
  assetId: string | null;
};

const browserCodecIdentifiers: Readonly<Record<string, string>> = {
  ac3: 'ac-3',
  alac: 'alac',
  eac3: 'ec-3',
  flac: 'flac',
  mp3: 'mp3',
  opus: 'opus',
  vorbis: 'vorbis'
};

export function mergeAudioLoadIntent(current: AudioLoadIntent, next: Partial<AudioLoadIntent>): AudioLoadIntent {
  return {
    autoplay: current.autoplay || Boolean(next.autoplay),
    chapterId: next.chapterId === undefined ? current.chapterId : next.chapterId,
    assetId: next.assetId === undefined ? current.assetId : next.assetId
  };
}

export function unsupportedAudioMimeType(
  mimeType: string,
  codec: string | null,
  canPlayType: (mime: string) => CanPlayTypeResult
) {
  const normalized = mimeType.split(';', 1)[0]?.trim().toLowerCase() ?? '';
  if (!normalized.startsWith('audio/')) return null;
  const normalizedCodec = codec?.trim().toLowerCase() ?? '';
  const codecIdentifier = browserCodecIdentifiers[normalizedCodec]
    ?? (normalized.startsWith('audio/wav') && normalizedCodec.startsWith('pcm_') ? '1' : null);
  if (codecIdentifier) {
    const capabilityType = `${normalized}; codecs="${codecIdentifier}"`;
    return canPlayType(capabilityType) ? null : capabilityType;
  }
  if (normalizedCodec) return null;
  return canPlayType(normalized) ? null : normalized;
}

export function audioFormatLabel(track: Pick<AudioTrack, 'mimeType' | 'codec'>) {
  return track.codec ? `${track.mimeType} · ${track.codec}` : track.mimeType;
}

export function nextAudioTrackForMetadataPreload(tracks: AudioTrack[], trackIndex: number) {
  return trackIndex >= 0 && trackIndex < tracks.length - 1 ? tracks[trackIndex + 1] : null;
}

export function clamp(value: number, minimum: number, maximum: number) {
  if (!Number.isFinite(value)) return minimum;
  return Math.max(minimum, Math.min(maximum, value));
}

export function pendingSeekAfterAssignment(
  pendingPositionMs: number | null,
  observedPositionMs: number,
  assignmentSucceeded: boolean,
  toleranceMs = 500
) {
  if (pendingPositionMs === null) return null;
  return assignmentSucceeded && Math.abs(observedPositionMs - pendingPositionMs) <= toleranceMs
    ? null
    : pendingPositionMs;
}

export function beginAudioResourceSwitch(
  current: AudioPlaybackState,
  requestedResourceId: string,
  pendingSummary: AudioLaunchSummary | null = null
): AudioPlaybackState {
  return {
    ...current,
    lifecycle: 'loading',
    pendingResourceId: requestedResourceId,
    pendingSummary,
    loadError: null,
    error: null,
    safetyError: null
  };
}

export function failAudioResourceSwitch(
  previous: AudioPlaybackState,
  requestedResourceId: string,
  message: string,
  pendingSummary: AudioLaunchSummary | null = null,
  safetyError: AudioPlaybackState['safetyError'] = null
): AudioPlaybackState {
  return {
    ...previous,
    lifecycle: previous.bootstrap
      ? previous.lifecycle === 'playing' || previous.lifecycle === 'loading' ? 'paused' : previous.lifecycle
      : 'error',
    pendingResourceId: requestedResourceId,
    pendingSummary,
    loadError: message,
    safetyError
  };
}

export function formatAudioTime(milliseconds: number, compact = false) {
  const totalSeconds = Math.max(0, Math.floor((Number.isFinite(milliseconds) ? milliseconds : 0) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  if (compact) return `${minutes}:${String(seconds).padStart(2, '0')}`;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export function orderedTracks(tracks: AudioTrack[]) {
  return [...tracks].sort((left, right) => (
    left.sortOrder - right.sortOrder
    || left.assetId.localeCompare(right.assetId)
  ));
}

export function orderedChapters(chapters: AudioChapter[]) {
  return [...chapters].sort((left, right) => left.sortOrder - right.sortOrder || left.startMs - right.startMs || left.id.localeCompare(right.id));
}

export function trackOffsets(tracks: AudioTrack[]) {
  let elapsed = 0;
  return tracks.map((track) => {
    const offset = elapsed;
    elapsed += Math.max(0, track.durationMs);
    return offset;
  });
}

export function absolutePositionForTrack(tracks: AudioTrack[], trackIndex: number, positionMs: number) {
  if (tracks.length === 0) return 0;
  const index = Math.max(0, Math.min(tracks.length - 1, Math.round(trackIndex)));
  const offsets = trackOffsets(tracks);
  return offsets[index] + clamp(positionMs, 0, Math.max(0, tracks[index].durationMs));
}

export function targetForAbsolutePosition(tracks: AudioTrack[], absolutePositionMs: number) {
  if (tracks.length === 0) return { trackIndex: -1, positionMs: 0 };
  const total = tracks.reduce((sum, track) => sum + Math.max(0, track.durationMs), 0);
  const target = clamp(absolutePositionMs, 0, total);
  const offsets = trackOffsets(tracks);
  for (let index = tracks.length - 1; index >= 0; index -= 1) {
    if (target >= offsets[index]) {
      return {
        trackIndex: index,
        positionMs: clamp(target - offsets[index], 0, Math.max(0, tracks[index].durationMs))
      };
    }
  }
  return { trackIndex: 0, positionMs: 0 };
}

export function chapterAt(chapters: AudioChapter[], assetId: string, positionMs: number) {
  const candidates = chapters.filter((chapter) => chapter.assetId === assetId);
  if (candidates.length === 0) return null;
  return candidates.find((chapter) => positionMs >= chapter.startMs && positionMs < chapter.endMs)
    ?? [...candidates].reverse().find((chapter) => positionMs >= chapter.startMs)
    ?? candidates[0];
}

export function normalizeResumeTarget(bootstrap: AudioBootstrap) {
  const tracks = orderedTracks(bootstrap.tracks);
  const resume = bootstrap.resumeLocation;
  const resumeTrackIndex = resume ? tracks.findIndex((track) => track.assetId === resume.assetId) : -1;
  const trackIndex = resumeTrackIndex >= 0 ? resumeTrackIndex : 0;
  return {
    trackIndex,
    positionMs: resumeTrackIndex >= 0
      ? clamp(resume?.positionMs ?? 0, 0, Math.max(0, tracks[trackIndex]?.durationMs ?? 0))
      : 0
  };
}

export function audioProgressPercent(absolutePositionMs: number, totalDurationMs: number, completed = false) {
  if (completed) return 100;
  if (!(totalDurationMs > 0)) return 0;
  // Normal playback never fabricates completion. Only the final native ended
  // event passes completed=true.
  return clamp((absolutePositionMs / totalDurationMs) * 100, 0, 99.9999);
}

export function audioLocation(
  track: AudioTrack,
  chapter: AudioChapter | null,
  positionMs: number,
  resourceId: string
): AudioLocation {
  return {
    type: 'audio',
    resourceId,
    assetId: track.assetId,
    chapterId: chapter?.id ?? null,
    positionMs: Math.max(0, Math.round(positionMs))
  };
}
