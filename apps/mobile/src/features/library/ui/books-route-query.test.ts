import assert from 'node:assert/strict';
import test from 'node:test';

import { DEFAULT_BOOKS_QUERY } from '../model/library';
import {
  booksQueriesMatch,
  booksRouteParametersMatch,
  decodeBooksRouteQuery,
  encodeBooksRouteQuery,
} from './books-route-query';

test('decodes every URL-owned books query field', () => {
  const decoded = decodeBooksRouteQuery(
    {
      search: '  Austen  ',
      status: 'UNREAD',
      mediaKind: 'EBOOK',
      sort: 'title',
      direction: 'asc',
      view: 'list',
      shelfId: ' shelf-1 ',
    },
    DEFAULT_BOOKS_QUERY,
  );

  assert.deepEqual(decoded, {
    search: 'Austen',
    status: 'UNREAD',
    mediaKind: 'EBOOK',
    sort: 'title',
    direction: 'asc',
    view: 'list',
    shelfId: 'shelf-1',
  });
});

test('falls back for invalid enums without accepting unchecked URL input', () => {
  const fallback = {
    ...DEFAULT_BOOKS_QUERY,
    status: 'READING' as const,
    mediaKind: 'COMIC' as const,
    sort: 'author' as const,
    direction: 'asc' as const,
    view: 'list' as const,
  };
  const decoded = decodeBooksRouteQuery(
    {
      status: 'BROKEN',
      mediaKind: 'VIDEO',
      sort: 'popular',
      direction: 'sideways',
      view: 'cards',
    },
    fallback,
  );

  assert.deepEqual(decoded, fallback);
});

test('empty URL values deliberately clear nullable filters and shelf', () => {
  const decoded = decodeBooksRouteQuery(
    {
      search: '',
      status: '',
      mediaKind: '',
      shelfId: '',
    },
    {
      ...DEFAULT_BOOKS_QUERY,
      search: 'prior',
      status: 'FINISHED',
      mediaKind: 'AUDIOBOOK',
      shelfId: 'shelf-2',
    },
  );

  assert.equal(decoded.search, '');
  assert.equal(decoded.status, null);
  assert.equal(decoded.mediaKind, null);
  assert.equal(decoded.shelfId, null);
});

test('rejects an overlong shelf id instead of truncating it to another id', () => {
  const decoded = decodeBooksRouteQuery(
    { shelfId: 'x'.repeat(192) },
    { ...DEFAULT_BOOKS_QUERY, shelfId: 'safe-shelf' },
  );

  assert.equal(decoded.shelfId, 'safe-shelf');
});

test('encoding writes all fields and supports stable equality checks', () => {
  const encoded = encodeBooksRouteQuery(DEFAULT_BOOKS_QUERY);

  assert.deepEqual(encoded, {
    search: '',
    status: '',
    mediaKind: '',
    sort: 'recent_read',
    direction: 'desc',
    view: 'grid',
    shelfId: '',
  });
  assert.equal(booksRouteParametersMatch(encoded, encoded), true);
  assert.equal(
    booksQueriesMatch(
      DEFAULT_BOOKS_QUERY,
      decodeBooksRouteQuery(encoded, DEFAULT_BOOKS_QUERY),
    ),
    true,
  );
});
