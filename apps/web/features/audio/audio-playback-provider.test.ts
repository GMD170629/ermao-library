import assert from 'node:assert/strict';
import test from 'node:test';
import audioFixture from '../../../../packages/reader-contracts/fixtures/reader-v5/audio.json';
import { normalizeAudioBootstrap } from './api';
import { audioLocationFromPosition, audioPositionReport } from './audio-playback-provider';
import { parseStandardReaderLocator } from '../../lib/reader/v5-locator';

function bootstrap() {
  return normalizeAudioBootstrap({
    ok: true,
    data: {
      schemaVersion: 5,
      userId: 'user-1',
      readerType: 'audio',
      resourceUrl: '/api/reader/v5/resources/resource-1/publication',
      book: { id: 'book-1', title: 'Audio' },
      resource: { id: 'resource-1', bookId: 'book-1', title: 'Audio', durationMs: 723_000, chapterCount: 1 },
      availableResources: [],
      assets: [1, 2, 3].map((index) => ({
        id: `asset-${index}`,
        title: `Track ${index}`,
        mimeType: 'audio/mp4',
        durationMs: 241_000,
        sortOrder: index - 1,
        url: `/api/assets/asset-${index}`
      })),
      units: [{ id: 'chapter-3', title: '第三章', assetId: 'asset-3', startMs: 0, endMs: 241_000, index: 2 }],
      progressSnapshot: null
    }
  }, 'resource-1');
}

test('audio adapter captures a standard Locator with the bootstrap asset URL', () => {
  const value = bootstrap();
  const track = value.tracks[2];
  assert.ok(track);
  const position = audioPositionReport(value, track, value.chapters[0] ?? null, 120_500, 35);
  const locator = parseStandardReaderLocator(position.locator);
  assert.ok(locator);
  assert.equal(locator.href, '/api/assets/asset-3');
  assert.equal(locator.locations.position, 3);
  assert.equal(locator.locations.time, 120.5);
  assert.equal(position.presentation.currentHref, '/api/assets/asset-3');
});

test('audio adapter restores by Locator position and time, independent of presentation percent', () => {
  const value = bootstrap();
  const position = {
    ...audioFixture.position,
    presentation: { ...audioFixture.position.presentation, displayPercent: 99, totalProgression: 0.99 }
  } as const;
  const location = audioLocationFromPosition(position, value);
  assert.deepEqual(location, {
    type: 'audio',
    resourceId: 'resource-1',
    assetId: 'asset-3',
    chapterId: 'chapter-3',
    positionMs: 120_500
  });
});
