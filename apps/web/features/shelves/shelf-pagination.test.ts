import assert from 'node:assert/strict';
import test from 'node:test';
import {
  clampShelfPage,
  shelfPageCount,
  shelfPageItems,
  shelfPaginationCandidates
} from './shelf-pagination';

test('书架详情按每页 20 本分页', () => {
  const books = Array.from({ length: 45 }, (_, index) => index + 1);

  assert.equal(shelfPageCount(books.length), 3);
  assert.deepEqual(shelfPageItems(books, 1), books.slice(0, 20));
  assert.deepEqual(shelfPageItems(books, 2), books.slice(20, 40));
  assert.deepEqual(shelfPageItems(books, 3), books.slice(40));
});

test('页码会限制在有效范围内', () => {
  assert.equal(clampShelfPage(0, 45), 1);
  assert.equal(clampShelfPage(99, 45), 3);
  assert.equal(clampShelfPage(3, 0), 1);
});

test('分页页码保留首尾和当前页附近页码', () => {
  assert.deepEqual(shelfPaginationCandidates(1, 10), [1, 2, 10]);
  assert.deepEqual(shelfPaginationCandidates(5, 10), [1, 4, 5, 6, 10]);
  assert.deepEqual(shelfPaginationCandidates(10, 10), [1, 9, 10]);
});
