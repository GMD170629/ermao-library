import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeAudioBootstrap } from './api';
import { absolutePositionForTrack, beginAudioResourceSwitch, failAudioResourceSwitch, orderedTracks, targetForAbsolutePosition, unsupportedAudioMimeType } from './audio-model';
import type { AudioPlaybackState } from './types';

const payload = {
  ok: true,
  data: {
    schemaVersion: 4,
    userId: 'user-1',
    readerType: 'audio',
    book: { id: 'book-1', title: '有声书', author: '作者' },
    resource: { id: 'resource-1', bookId: 'book-1', title: '第一资源', sortOrder: 0, durationMs: 30_000, chapterCount: 1, resourceCompleted: false },
    availableResources: [
      { id: 'resource-1', bookId: 'book-1', title: '第一资源', sortOrder: 0, chapterCount: 1, durationMs: 30_000, resourceCompleted: false },
      { id: 'resource-2', bookId: 'book-1', title: '第二资源', sortOrder: 1, chapterCount: 0, durationMs: 0, resourceCompleted: true }
    ],
    assets: [
      { id: 'asset-1', title: '精绝古城 01', mimeType: 'audio/mpeg', codec: 'mp3', durationMs: 10_000, sortOrder: 0, url: '/api/assets/asset-1' },
      { id: 'asset-2', mimeType: 'audio/mpeg', durationMs: 20_000, sortOrder: 1, url: '/api/assets/asset-2' }
    ],
    units: [{ id: 'chapter-1', title: '第一章', assetId: 'asset-1', startMs: 0, endMs: 10_000, index: 0 }],
    progressSnapshot: {
      schemaVersion: 4,
      revision: 3,
      receivedAtEpochMillis: 100,
      displayPercent: 50,
      locator: {
        kind: 'audio',
        assetId: 'asset-2',
        positionMillis: 7_000
      }
    }
  }
};

test('normalizes the resource-first Reader v4 audio bootstrap', () => {
  const bootstrap = normalizeAudioBootstrap(payload, 'resource-1');
  assert.equal(bootstrap.schemaVersion, 4);
  assert.equal(bootstrap.resource.id, 'resource-1');
  assert.deepEqual(bootstrap.availableResources.map((resource) => resource.id), ['resource-1', 'resource-2']);
  assert.equal(bootstrap.resumeLocation?.resourceId, 'resource-1');
  assert.equal(bootstrap.tracks[0]?.codec, 'mp3');
  assert.equal(bootstrap.tracks[0]?.title, '精绝古城 01');
  assert.equal(bootstrap.tracks[1]?.title, '音轨 2');
  assert.equal(bootstrap.tracks[1]?.codec, null);
  assert.equal(bootstrap.totalDurationMs, 30_000);
});

test('maps between track and absolute time', () => {
  const tracks = normalizeAudioBootstrap(payload, 'resource-1').tracks;
  assert.equal(absolutePositionForTrack(tracks, 1, 5_000), 15_000);
  assert.deepEqual(targetForAbsolutePosition(tracks, 15_000), { trackIndex: 1, positionMs: 5_000 });
});

test('orders tracks only by the canonical server sort order', () => {
  const tracks = normalizeAudioBootstrap(payload, 'resource-1').tracks;
  const conflicting = [
    { ...tracks[0], sortOrder: 1, discNumber: 1, trackNumber: 1 },
    { ...tracks[1], sortOrder: 0, discNumber: 99, trackNumber: 99 }
  ];

  assert.deepEqual(orderedTracks(conflicting).map((track) => track.assetId), ['asset-2', 'asset-1']);
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

test('resource switching keeps the previous playback until the request commits or fails', () => {
  const bootstrap = normalizeAudioBootstrap(payload, 'resource-1');
  const previous: AudioPlaybackState = { lifecycle: 'playing', bootstrap, resourceId: bootstrap.resource.id, pendingResourceId: null, pendingSummary: null, loadError: null, bookId: bootstrap.book.id, trackIndex: 0, track: bootstrap.tracks[0] ?? null, chapter: null, positionMs: 0, durationMs: 10_000, absolutePositionMs: 0, totalDurationMs: 30_000, playbackRate: 1, skipBackwardSeconds: 15, skipForwardSeconds: 30, volume: 1, sleepTimerEndsAt: null, sleepTimerMode: null, error: null };
  const loading = beginAudioResourceSwitch(previous, 'resource-2');
  assert.equal(loading.resourceId, 'resource-1');
  assert.equal(loading.pendingResourceId, 'resource-2');
  const failed = failAudioResourceSwitch(previous, 'resource-2', '启动失败');
  assert.equal(failed.resourceId, 'resource-1');
  assert.equal(failed.pendingResourceId, 'resource-2');
  assert.equal(failed.lifecycle, 'paused');
});
