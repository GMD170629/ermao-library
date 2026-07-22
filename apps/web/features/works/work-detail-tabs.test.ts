import assert from 'node:assert/strict';
import test from 'node:test';
import type { WorkView } from '../../types/work';
import {
  audioDetailProjection,
  detailTabsForBook,
  formatDuration,
  moveWorkDetailTab,
  normalizeWorkDetailTabOrder,
  placeWorkDetailTab,
  resolvedDetailTab
} from './work-detail-tabs';

function legacyBook(editions: WorkView['editions']): WorkView {
  return { editions } as WorkView;
}

function edition(id: string, formatValue: WorkView['formatValue']): WorkView['editions'][number] {
  return { id, formatValue, hidden: false } as WorkView['editions'][number];
}

test('normalizes saved order, removes unknown duplicates and restores missing tabs', () => {
  assert.deepEqual(
    normalizeWorkDetailTabOrder('["AUDIOBOOK","EBOOK","AUDIOBOOK","UNKNOWN"]'),
    ['AUDIOBOOK', 'EBOOK', 'COMIC', 'STRUCTURE']
  );
});

test('legacy work hides missing media tabs and always keeps content structure', () => {
  const book = legacyBook([edition('epub', 'EPUB'), edition('audio', 'AUDIO')]);
  assert.deepEqual(detailTabsForBook(book).map((tab) => tab.key), ['EBOOK', 'AUDIOBOOK', 'STRUCTURE']);
});

test('API tab order wins and a hidden remembered tab falls back to first visible tab', () => {
  const book = {
    ...legacyBook([edition('epub', 'EPUB')]),
    selectedDetailTab: 'COMIC',
    detailTabs: [
      { key: 'STRUCTURE', label: '内容结构', sortOrder: 2 },
      { key: 'EBOOK', label: '电子书', sortOrder: 1 }
    ]
  } satisfies WorkView;
  assert.deepEqual(detailTabsForBook(book).map((tab) => tab.key), ['EBOOK', 'STRUCTURE']);
  assert.equal(resolvedDetailTab(book), 'EBOOK');
  assert.equal(resolvedDetailTab(book, 'STRUCTURE'), 'STRUCTURE');
});

test('stale API tabs cannot expose a missing media player', () => {
  const book = {
    ...legacyBook([edition('epub', 'EPUB')]),
    detailTabs: [
      { key: 'AUDIOBOOK', label: '有声书', sortOrder: 0 },
      { key: 'EBOOK', label: '电子书', sortOrder: 1 },
      { key: 'STRUCTURE', label: '内容结构', sortOrder: 2 }
    ]
  } satisfies WorkView;
  assert.deepEqual(detailTabsForBook(book).map((tab) => tab.key), ['EBOOK', 'STRUCTURE']);
  assert.equal(resolvedDetailTab(book, 'AUDIOBOOK'), 'EBOOK');
});

test('reorders tabs without losing any tab', () => {
  assert.deepEqual(
    moveWorkDetailTab(['EBOOK', 'COMIC', 'AUDIOBOOK', 'STRUCTURE'], 'AUDIOBOOK', -1),
    ['EBOOK', 'AUDIOBOOK', 'COMIC', 'STRUCTURE']
  );
  assert.deepEqual(
    placeWorkDetailTab(['EBOOK', 'COMIC', 'AUDIOBOOK', 'STRUCTURE'], 'STRUCTURE', 'COMIC'),
    ['EBOOK', 'STRUCTURE', 'COMIC', 'AUDIOBOOK']
  );
});

test('formats audiobook durations for chapter rows and hero summaries', () => {
  assert.equal(formatDuration(65_000), '1:05');
  assert.equal(formatDuration(3_665_000), '1:01:05');
  assert.equal(formatDuration(null), '');
});

test('projects only the matching audiobook edition into detail progress and chapter state', () => {
  const playback = {
    bootstrap: {
      book: { id: 'work-1' },
      edition: { id: 'audio-1', workId: 'work-1' },
      totalDurationMs: 100_000,
      progressPercent: 5
    },
    absolutePositionMs: 25_000,
    totalDurationMs: 100_000,
    positionMs: 5_000,
    track: { fileId: 'track-1', title: '第一轨' },
    chapter: { id: 'chapter-2', fileId: 'track-1', title: '第二章', startMs: 4_000 }
  } as Parameters<typeof audioDetailProjection>[3];

  assert.deepEqual(audioDetailProjection('AUDIOBOOK', 'work-1', 'audio-1', playback), {
    progress: 25,
    positionLabel: '第二章 · 0:05',
    currentChapterId: 'chapter-2',
    currentFileId: 'track-1',
    currentChapterStartMs: 4_000
  });
  assert.equal(audioDetailProjection('EBOOK', 'work-1', 'audio-1', playback), null);
  assert.equal(audioDetailProjection('AUDIOBOOK', 'work-1', 'audio-2', playback), null);
  assert.equal(audioDetailProjection('AUDIOBOOK', 'work-2', 'audio-1', playback), null);
});
