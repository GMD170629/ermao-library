import assert from 'node:assert/strict';
import test from 'node:test';
import type { ReadableResourceView } from '../../../types/book';
import { currentPositionLabel } from './current-position-label';
import type { ResourceDetailPage } from './resource-detail';

const resource = {
  id: 'resource-1',
  title: '测试图书',
  readerType: 'reflowable',
  format: 'EPUB',
  progress: 15,
  chapterCount: 7
} as ReadableResourceView;

const translate = (source: string, values?: Record<string, string | number>) => (
  source.replace('{value0}', String(values?.value0 ?? ''))
);

test('shows the exact Publication chapter title instead of estimating from percent', () => {
  const detail = {
    chapterCount: 12,
    units: [],
    page: { page: 1, pageSize: 120, total: 7, totalPages: 1 },
    currentHref: 'text/part0008_split_000.html',
    currentChapterIndex: 4,
    currentChapterTitle: '第四部 事件',
    currentChapterSortOrder: 4,
    currentPageNumber: null,
    progress: 15
  } satisfies ResourceDetailPage;

  assert.equal(currentPositionLabel(resource, detail, translate), '第四部 事件');
});

test('does not fabricate a chapter number while exact navigation is unavailable', () => {
  assert.equal(currentPositionLabel(resource, null, translate), '测试图书');
});

test('uses the confirmed server playback position when no local pending report exists', () => {
  const audio: ReadableResourceView = { ...resource, readerType: 'audio', durationMs: null, progress: 50 };
  const presentation = {
    displayPercent: 50, totalProgression: 0.5, currentHref: '/api/assets/audio-1',
    chapter: null, page: null, playback: { positionMillis: 15_000, durationMillis: 30_000 }
  };
  const detail: ResourceDetailPage = {
    presentation, chapterCount: null, units: [],
    page: { page: 1, pageSize: 50, total: 1, totalPages: 1 },
    currentHref: presentation.currentHref, currentChapterIndex: null, currentChapterTitle: null,
    currentChapterSortOrder: null, currentPageNumber: null, progress: 50
  };
  assert.equal(currentPositionLabel(audio, detail, translate), '0:15');
  const pending = { ...presentation, playback: { positionMillis: 5_000, durationMillis: 30_000 } };
  assert.equal(currentPositionLabel(audio, detail, translate, pending), '0:05');
  assert.equal(currentPositionLabel({ ...audio, durationMs: 1_000_000, progress: 99 }, detail, translate), '0:15');
});
