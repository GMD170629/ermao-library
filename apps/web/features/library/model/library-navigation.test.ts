import assert from 'node:assert/strict';
import test from 'node:test';
import { libraryReturnHref, workDetailHrefFromLibrary } from './library-navigation';

test('preserves the active library query when opening work details', () => {
  const detailHref = workDetailHrefFromLibrary(
    'work/下一部',
    'status=READING&sort=title&sortDirection=desc'
  );
  const detailUrl = new URL(detailHref, 'https://example.test');

  assert.equal(detailUrl.pathname, '/works/work%2F%E4%B8%8B%E4%B8%80%E9%83%A8');
  assert.equal(
    detailUrl.searchParams.get('returnTo'),
    '/library?status=READING&sort=title&sortDirection=desc'
  );
});

test('does not reopen the upload dialog when returning from work details', () => {
  assert.equal(
    libraryReturnHref('upload=1&search=%E6%8E%A8%E7%90%86'),
    '/library?search=%E6%8E%A8%E7%90%86'
  );
});
