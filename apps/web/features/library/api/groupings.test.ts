import assert from 'node:assert/strict';
import test from 'node:test';
import { parseLibraryGroupingPage } from './groupings';

test('parses paginated library groupings', () => {
  const page = parseLibraryGroupingPage({
    groups: [{
      id: 'series-1',
      name: '星海丛书',
      bookCount: 2,
      updatedAt: '2026-07-29T00:00:00Z'
    }],
    page: 1,
    pageSize: 48,
    total: 1,
    totalPages: 1
  });

  assert.equal(page.groups[0]?.name, '星海丛书');
  assert.equal(page.groups[0]?.bookCount, 2);
  assert.equal(page.total, 1);
});

test('rejects malformed library grouping counts', () => {
  assert.throws(
    () => parseLibraryGroupingPage({
      groups: [{
        id: 'author-1',
        name: '林川',
        bookCount: '2',
        updatedAt: '2026-07-29T00:00:00Z'
      }],
      page: 1,
      pageSize: 48,
      total: 1,
      totalPages: 1
    }),
    /Invalid library grouping field/
  );
});
