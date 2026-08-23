import assert from 'node:assert/strict';
import test from 'node:test';
import { librarySourceHref } from './library-source-navigation';

test('library source navigation creates an exact library filter', () => {
  const href = librarySourceHref({ id: 'library/a', name: '家庭书库' });
  const url = new URL(href, 'https://example.test');

  assert.equal(url.pathname, '/library');
  assert.equal(url.searchParams.get('libraryName'), '家庭书库');
  assert.deepEqual(JSON.parse(url.searchParams.get('filters') ?? ''), {
    combinator: 'ALL',
    conditions: [{ field: 'library', operator: 'equals', value: 'library/a' }]
  });
});
