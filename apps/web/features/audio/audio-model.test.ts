import assert from 'node:assert/strict';
import test from 'node:test';
import {
  absolutePositionForTrack,
  audioProgressPercent,
  beginAudioEditionSwitch,
  chapterAt,
  failAudioEditionSwitch,
  formatAudioTime,
  mergeAudioLoadIntent,
  nextAudioTrackForMetadataPreload,
  normalizeResumeTarget,
  pendingSeekAfterAssignment,
  targetForAbsolutePosition,
  unsupportedAudioMimeType
} from './audio-model';
import { normalizeAudioBootstrap } from './api';
import type { AudioPlaybackState } from './types';

const bootstrap = normalizeAudioBootstrap({
  schemaVersion: 2,
  readerType: 'audio',
  userId: 'user-1',
  contentFingerprint: 'sha256:audio',
  book: { id: 'work-1', title: '三体', author: '刘慈欣' },
  edition: { id: 'edition-1', workId: 'work-1', versionName: '完整有声版', narrator: '王明' },
  selectedVolume: { id: 'volume-1', title: '第一卷' },
  volumes: [
    { id: 'volume-1', title: '第一卷', index: 0, chapterCount: 2, durationMs: 30_000 },
    { id: 'volume-2', title: '第二卷', index: 1, chapterCount: 1, durationMs: 20_000 }
  ],
  tracks: [
    { fileId: 'file-2', title: '下', url: '/api/files/file-2', mimeType: 'audio/mp4', durationMs: 20_000, sortOrder: 2 },
    { fileId: 'file-1', title: '上', url: '/api/files/file-1', mimeType: 'audio/mpeg', durationMs: 10_000, sortOrder: 1 }
  ],
  chapters: [
    { id: 'chapter-2', title: '第二章', fileId: 'file-1', startMs: 5_000, endMs: 10_000, sortOrder: 2 },
    { id: 'chapter-1', title: '第一章', fileId: 'file-1', startMs: 0, endMs: 5_000, sortOrder: 1 }
  ],
  totalDurationMs: 30_000,
  resumeLocation: { type: 'audio', fileId: 'file-2', chapterId: null, positionMs: 7_000, volumeId: null },
  progressPercent: 56
});

test('normalizes and orders audio bootstrap tracks and chapters', () => {
  assert.equal(bootstrap.schemaVersion, 2);
  assert.deepEqual(bootstrap.tracks.map((track) => track.fileId), ['file-1', 'file-2']);
  assert.deepEqual(bootstrap.chapters.map((chapter) => chapter.id), ['chapter-1', 'chapter-2']);
  assert.equal(bootstrap.volumeId, 'volume-1');
  assert.deepEqual(bootstrap.volumes.map((volume) => volume.id), ['volume-1', 'volume-2']);
  assert.deepEqual(normalizeResumeTarget(bootstrap), { trackIndex: 1, positionMs: 7_000 });
});

test('rejects an unsupported audio bootstrap wire schema without confusing it with preference schema V3', () => {
  assert.throws(() => normalizeAudioBootstrap({
    schemaVersion: 3,
    readerType: 'audio',
    book: { id: 'work-1', title: '三体' },
    edition: { id: 'edition-1', workId: 'work-1' },
    tracks: [{ fileId: 'file-1', durationMs: 1_000 }]
  }), /不支持这个有声书启动协议版本/);
});

test('maps between track time and edition absolute time across boundaries', () => {
  assert.equal(absolutePositionForTrack(bootstrap.tracks, 1, 2_500), 12_500);
  assert.deepEqual(targetForAbsolutePosition(bootstrap.tracks, 9_999), { trackIndex: 0, positionMs: 9_999 });
  assert.deepEqual(targetForAbsolutePosition(bootstrap.tracks, 10_000), { trackIndex: 1, positionMs: 0 });
  assert.deepEqual(targetForAbsolutePosition(bootstrap.tracks, 99_000), { trackIndex: 1, positionMs: 20_000 });
});

test('finds chapters and never reports completion before the final ended event', () => {
  assert.equal(chapterAt(bootstrap.chapters, 'file-1', 5_001)?.id, 'chapter-2');
  assert.equal(audioProgressPercent(30_000, 30_000), 99.9999);
  assert.equal(audioProgressPercent(30_000, 30_000, true), 100);
});

test('formats short and long durations for player labels', () => {
  assert.equal(formatAudioTime(65_000), '01:05');
  assert.equal(formatAudioTime(3_665_000), '1:01:05');
});

test('clears a pending restore seek only after the media element accepts it', () => {
  assert.equal(pendingSeekAfterAssignment(42_000, 42_000, true), null);
  assert.equal(pendingSeekAfterAssignment(42_000, 0, true), 42_000);
  assert.equal(pendingSeekAfterAssignment(42_000, 42_000, false), 42_000);
  assert.equal(pendingSeekAfterAssignment(null, 10_000, true), null);
});

test('a passive route bootstrap cannot erase a user initiated audio load intent', () => {
  const userIntent = { autoplay: true, chapterId: 'chapter-2' };
  assert.deepEqual(mergeAudioLoadIntent(userIntent, { autoplay: false }), userIntent);
  assert.deepEqual(
    mergeAudioLoadIntent({ autoplay: false, chapterId: null }, { autoplay: true, chapterId: 'chapter-1' }),
    { autoplay: true, chapterId: 'chapter-1' }
  );
});

test('checks declared audio MIME support and preloads only the next track metadata', () => {
  assert.equal(unsupportedAudioMimeType('audio/mp4; codecs="mp4a.40.2"', () => 'probably'), null);
  assert.equal(unsupportedAudioMimeType('audio/x-unsupported', () => ''), 'audio/x-unsupported');
  assert.equal(unsupportedAudioMimeType('application/octet-stream', () => ''), null);
  assert.equal(nextAudioTrackForMetadataPreload(bootstrap.tracks, 0)?.fileId, 'file-2');
  assert.equal(nextAudioTrackForMetadataPreload(bootstrap.tracks, 1), null);
});

test('edition switching retains the old identity until commit and restores it paused on failure', () => {
  const previous: AudioPlaybackState = {
    lifecycle: 'playing',
    bootstrap,
    editionId: bootstrap.edition.id,
    pendingEditionId: null,
    pendingSummary: null,
    loadError: null,
    workId: bootstrap.edition.workId,
    trackIndex: 1,
    track: bootstrap.tracks[1],
    chapter: null,
    positionMs: 7_000,
    durationMs: 20_000,
    absolutePositionMs: 17_000,
    totalDurationMs: 30_000,
    playbackRate: 1.25,
    skipBackwardSeconds: 15,
    skipForwardSeconds: 30,
    volume: 0.8,
    sleepTimerEndsAt: null,
    sleepTimerMode: null,
    error: null
  };
  const launchSummary = {
    editionId: 'edition-2',
    workId: 'work-2',
    title: '待加载有声书',
    author: '作者',
    coverUrl: '/cover.jpg',
    versionName: '演播版',
    narrator: '演播者'
  };
  const loading = beginAudioEditionSwitch(previous, 'edition-2', launchSummary);
  assert.equal(loading.editionId, 'edition-1');
  assert.equal(loading.bootstrap?.edition.id, 'edition-1');
  assert.equal(loading.pendingEditionId, 'edition-2');
  assert.deepEqual(loading.pendingSummary, launchSummary);
  assert.equal(loading.lifecycle, 'loading');

  const restored = failAudioEditionSwitch(previous, 'edition-2', '启动失败', launchSummary);
  assert.equal(restored.editionId, 'edition-1');
  assert.equal(restored.absolutePositionMs, 17_000);
  assert.equal(restored.pendingEditionId, 'edition-2');
  assert.equal(restored.loadError, '启动失败');
  assert.deepEqual(restored.pendingSummary, launchSummary);
  assert.equal(restored.lifecycle, 'paused');
  assert.notEqual(restored.lifecycle, 'playing');

  const failedInitialLoad = failAudioEditionSwitch({ ...previous, lifecycle: 'idle', bootstrap: null, editionId: null, workId: null }, 'edition-2', '启动失败');
  assert.equal(failedInitialLoad.lifecycle, 'error');
  assert.equal(failedInitialLoad.editionId, null);
});
