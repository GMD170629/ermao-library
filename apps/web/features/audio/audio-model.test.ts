import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeAudioBootstrap } from './api';
import { absolutePositionForTrack, beginAudioVolumeSwitch, failAudioVolumeSwitch, targetForAbsolutePosition, unsupportedAudioMimeType } from './audio-model';
import type { AudioPlaybackState } from './types';

const payload = {
  ok: true,
  data: {
    schemaVersion: 4,
    userId: 'user-1',
    readerType: 'audio',
    contentFingerprint: 'fingerprint-1',
    publicationFingerprint: {
      originalFileHash: 'sha256:' + 'a'.repeat(64),
      parser: 'audio-index:1',
      normalization: 'shuku-audio-v1'
    },
    book: { id: 'work-1', title: '有声书', author: '作者' },
    mediaVersion: { id: 'media-audio', workId: 'work-1', mediaKind: 'AUDIOBOOK', completed: false },
    volume: { id: 'volume-1', mediaVersionId: 'media-audio', title: '第一卷', sortOrder: 0, durationMs: 30_000 },
    availableVolumes: [
      { id: 'volume-1', mediaVersionId: 'media-audio', title: '第一卷', sortOrder: 0 },
      { id: 'volume-2', mediaVersionId: 'media-audio', title: '第二卷', sortOrder: 1 }
    ],
    files: [
      { id: 'file-1', mimeType: 'audio/mpeg', codec: 'mp3', durationMs: 10_000, sortOrder: 0, url: '/api/files/file-1' },
      { id: 'file-2', mimeType: 'audio/mpeg', durationMs: 20_000, sortOrder: 1, url: '/api/files/file-2' }
    ],
    units: [{ id: 'chapter-1', title: '第一章', fileId: 'file-1', startMs: 0, endMs: 10_000, index: 0 }],
    progressSnapshot: {
      schemaVersion: 4,
      revision: 3,
      receivedAtEpochMillis: 100,
      displayPercent: 50,
      locator: {
        kind: 'audio',
        publication: {
          originalFileHash: 'sha256:' + 'a'.repeat(64),
          parser: 'audio-index:1',
          normalization: 'shuku-audio-v1'
        },
        fileId: 'file-2',
        positionMillis: 7_000
      }
    }
  }
};

test('normalizes the volume-first Reader v4 audio bootstrap', () => {
  const bootstrap = normalizeAudioBootstrap(payload, 'volume-1');
  assert.equal(bootstrap.schemaVersion, 4);
  assert.equal(bootstrap.volume.id, 'volume-1');
  assert.deepEqual(bootstrap.availableVolumes.map((volume) => volume.id), ['volume-1', 'volume-2']);
  assert.equal(bootstrap.resumeLocation?.volumeId, 'volume-1');
  assert.equal(bootstrap.tracks[0]?.codec, 'mp3');
  assert.equal(bootstrap.tracks[1]?.codec, null);
});

test('maps between track and absolute time', () => {
  const tracks = normalizeAudioBootstrap(payload, 'volume-1').tracks;
  assert.equal(absolutePositionForTrack(tracks, 1, 5_000), 15_000);
  assert.deepEqual(targetForAbsolutePosition(tracks, 15_000), { trackIndex: 1, positionMs: 5_000 });
});

test('checks known codecs with a codec-qualified MIME type', () => {
  const checked: string[] = [];
  const unsupported = unsupportedAudioMimeType('audio/ogg', 'opus', (value) => {
    checked.push(value);
    return '';
  });
  assert.equal(unsupported, 'audio/ogg; codecs="opus"');
  assert.deepEqual(checked, ['audio/ogg; codecs="opus"']);
});

test('lets the media element decide unknown codec support', () => {
  let checks = 0;
  const unsupported = unsupportedAudioMimeType('audio/x-ape', 'ape', () => {
    checks += 1;
    return '';
  });
  assert.equal(unsupported, null);
  assert.equal(checks, 0);
});

test('volume switching keeps the previous playback until the request commits or fails', () => {
  const bootstrap = normalizeAudioBootstrap(payload, 'volume-1');
  const previous: AudioPlaybackState = { lifecycle: 'playing', bootstrap, volumeId: bootstrap.volume.id, pendingVolumeId: null, pendingSummary: null, loadError: null, workId: bootstrap.mediaVersion.workId, trackIndex: 0, track: bootstrap.tracks[0] ?? null, chapter: null, positionMs: 0, durationMs: 10_000, absolutePositionMs: 0, totalDurationMs: 30_000, playbackRate: 1, skipBackwardSeconds: 15, skipForwardSeconds: 30, volume: 1, sleepTimerEndsAt: null, sleepTimerMode: null, error: null };
  const loading = beginAudioVolumeSwitch(previous, 'volume-2');
  assert.equal(loading.volumeId, 'volume-1');
  assert.equal(loading.pendingVolumeId, 'volume-2');
  const failed = failAudioVolumeSwitch(previous, 'volume-2', '启动失败');
  assert.equal(failed.volumeId, 'volume-1');
  assert.equal(failed.pendingVolumeId, 'volume-2');
  assert.equal(failed.lifecycle, 'paused');
});
