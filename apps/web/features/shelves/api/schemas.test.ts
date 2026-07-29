import assert from 'node:assert/strict';
import test from 'node:test';
import { parseShelfView } from './schemas';

test('parses a collection shelf at the API boundary', () => {
  const shelf = parseShelfView({
    id: 'collection-travel',
    name: '旅行',
    description: '旅行相关书架',
    kind: 'COLLECTION',
    shelfCount: 2,
    memberShelfIds: ['shelf-a', 'shelf-b'],
    createdAt: '1970-01-01T00:00:00Z',
    updatedAt: '1970-01-01T00:00:00Z'
  });

  assert.equal(shelf.kind, 'COLLECTION');
  assert.equal(shelf.shelfCount, 2);
  assert.deepEqual(shelf.memberShelfIds, ['shelf-a', 'shelf-b']);
});
