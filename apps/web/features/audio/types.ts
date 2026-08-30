export type AudioTrack = {
  assetId: string;
  title: string;
  url: string;
  mimeType: string;
  codec: string | null;
  durationMs: number;
  discNumber: number | null;
  trackNumber: number | null;
  sortOrder: number;
};

export type AudioChapter = {
  id: string;
  title: string;
  assetId: string;
  startMs: number;
  endMs: number;
  sortOrder: number;
};

export type AudioLocation = {
  type: 'audio';
  resourceId: string;
  assetId: string;
  chapterId: string | null;
  positionMs: number;
};

export type AudioBookSummary = {
  id: string;
  title: string;
  author: string | null;
  coverUrl: string | null;
};

export type AudioResourceSummary = {
  id: string;
  bookId: string;
  title: string;
  sortOrder: number;
  chapterCount: number;
  durationMs: number;
  resourceCompleted: boolean;
};

export type AudioLaunchSummary = {
  resourceId: string;
  bookId: string;
  title: string;
  author: string | null;
  coverUrl: string | null;
  resourceTitle: string | null;
  narrator: string | null;
  chapterTitle?: string | null;
};

export type AudioBootstrap = {
  schemaVersion: 4;
  userId: string;
  readerType: 'audio';
  progressRevision: number;
  book: AudioBookSummary;
  resource: AudioResourceSummary;
  resourceCompleted: boolean;
  availableResources: AudioResourceSummary[];
  tracks: AudioTrack[];
  chapters: AudioChapter[];
  totalDurationMs: number;
  resumeLocation: AudioLocation | null;
  progressPercent: number;
  serverUpdatedAtEpochMillis: number | null;
  preferences: {
    playbackRate: number;
    skipBackwardSeconds: number;
    skipForwardSeconds: number;
    volume: number;
  };
};

export type AudioLifecycle = 'idle' | 'loading' | 'ready' | 'playing' | 'paused' | 'error';
export type AudioSleepTimerMode = 'timer' | 'chapter' | null;

export type AudioPlaybackState = {
  lifecycle: AudioLifecycle;
  bootstrap: AudioBootstrap | null;
  resourceId: string | null;
  pendingResourceId: string | null;
  pendingSummary: AudioLaunchSummary | null;
  loadError: string | null;
  bookId: string | null;
  trackIndex: number;
  track: AudioTrack | null;
  chapter: AudioChapter | null;
  positionMs: number;
  durationMs: number;
  absolutePositionMs: number;
  totalDurationMs: number;
  playbackRate: number;
  skipBackwardSeconds: number;
  skipForwardSeconds: number;
  volume: number;
  sleepTimerEndsAt: number | null;
  sleepTimerMode: AudioSleepTimerMode;
  error: string | null;
  safetyError: ReaderSafetyFailure | null;
};

export type LoadAudioResourceOptions = {
  autoplay?: boolean;
  force?: boolean;
  chapterId?: string;
  assetId?: string;
  summary?: AudioLaunchSummary;
};

export type AudioPlaybackContextValue = AudioPlaybackState & {
  loadResource: (resourceId: string, options?: LoadAudioResourceOptions) => Promise<void>;
  retry: () => Promise<void>;
  cancelResourceSwitch: () => void;
  play: () => Promise<void>;
  pause: () => void;
  toggle: () => Promise<void>;
  close: () => void;
  seekBy: (seconds: number) => void;
  seekTo: (positionMs: number) => void;
  seekToAbsolute: (positionMs: number) => void;
  previousChapter: () => void;
  nextChapter: () => void;
  selectChapter: (chapterId: string, autoplay?: boolean) => void;
  selectTrack: (trackIndex: number, autoplay?: boolean) => void;
  setPlaybackRate: (rate: number) => void;
  setVolume: (volume: number) => void;
  setSleepTimer: (value: number | 'chapter' | null) => void;
};
import type { ReaderSafetyFailure } from '@shuku/reader-core';
