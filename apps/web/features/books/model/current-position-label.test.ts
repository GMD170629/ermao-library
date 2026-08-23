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
