export type AudioTrack = {
  fileId: string;
  title: string;
  url: string;
  mimeType: string;
  codec: string | null;
  contentHash: string | null;
  durationMs: number;
  discNumber: number | null;
  trackNumber: number | null;
  sortOrder: number;
};

export type AudioChapter = {
  id: string;
  title: string;
  fileId: string;
  startMs: number;
  endMs: number;
  sortOrder: number;
};

export type AudioLocation = {
  type: 'audio';
  volumeId: string;
  fileId: string;
  chapterId: string | null;
  positionMs: number;
};

export type AudioBookSummary = {
  id: string;
  title: string;
  author: string | null;
  coverUrl: string | null;
};

export type AudioMediaVersionSummary = {
  id: string;
  workId: string;
  mediaKind: 'AUDIOBOOK';
  completed: boolean;
};

export type AudioVolumeSummary = {
  id: string;
  title: string;
  index: number;
  chapterCount: number;
  durationMs: number;
};

export type AudioLaunchSummary = {
  volumeId: string;
  workId: string;
  title: string;
  author: string | null;
  coverUrl: string | null;
  volumeTitle: string | null;
  narrator: string | null;
  chapterTitle?: string | null;
};

export type AudioBootstrap = {
  schemaVersion: 4;
  userId: string;
  readerType: 'audio';
  contentFingerprint: string;
  localContentFingerprint: string;
  book: AudioBookSummary;
  mediaVersion: AudioMediaVersionSummary;
  volume: AudioVolumeSummary;
  availableVolumes: AudioVolumeSummary[];
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
  volumeId: string | null;
  pendingVolumeId: string | null;
  pendingSummary: AudioLaunchSummary | null;
  loadError: string | null;
  workId: string | null;
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
};

export type LoadAudioVolumeOptions = {
  autoplay?: boolean;
  force?: boolean;
  chapterId?: string;
  summary?: AudioLaunchSummary;
};

export type AudioPlaybackContextValue = AudioPlaybackState & {
  loadVolume: (volumeId: string, options?: LoadAudioVolumeOptions) => Promise<void>;
  retry: () => Promise<void>;
  cancelVolumeSwitch: () => void;
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
