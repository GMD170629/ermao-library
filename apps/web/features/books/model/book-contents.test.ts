import assert from 'node:assert/strict';
import test from 'node:test';
import { mapBookContentsPage } from '../api/client';
import { bookContentSortQuery } from './book-contents';

test('book content controls map to stable server sorting', () => {
  assert.deepEqual(bookContentSortQuery('name-asc'), { sort: 'name', direction: 'asc' });
  assert.deepEqual(bookContentSortQuery('name-desc'), { sort: 'name', direction: 'desc' });
  assert.deepEqual(bookContentSortQuery('updated-desc'), { sort: 'updated', direction: 'desc' });
  assert.deepEqual(bookContentSortQuery('size-desc'), { sort: 'size', direction: 'desc' });
});

test('book contents remain usable when a rolling-upgrade response omits currentNode', () => {
  const page = mapBookContentsPage('book-1', 1, {
    bookId: 'book-1',
    currentSourceNodeId: null,
    currentResourceId: null,
    currentResourceIds: [],
    parentSourceNodeId: null,
    breadcrumbs: [],
    entries: [{
      sourceNodeId: 'version-1',
      parentSourceNodeId: 'root-1',
      name: 'version-one',
      title: '版本一',
      description: null,
      kind: 'FOLDER',
      physicalKind: 'DIRECTORY',
      sizeBytes: null,
      observedAt: '2026-08-22T00:00:00Z',
      hasChildren: true,
      resourceId: null,
      representativeResourceId: 'resource-1'
    }],
    page: 1,
    pageSize: 100,
    total: 1,
    totalPages: 1
  });

  assert.equal(page.currentNode, null);
  assert.equal(page.entries[0]?.title, '版本一');
});
