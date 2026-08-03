import assert from 'node:assert/strict';
import test from 'node:test';
import { topLevelShelves } from './navigation';
import type { ShelfView } from './types';

function shelf(
  id: string,
  kind: ShelfView['kind'],
  collectionIds: string[] = []
): ShelfView {
  return {
    id,
    kind,
    name: id,
    description: null,
    rulesStatus: 'VALID',
    unsupportedRuleFields: [],
    collectionIds,
    createdAt: '2026-07-29T00:00:00Z',
    updatedAt: '2026-07-29T00:00:00Z'
  };
}

test('topLevelShelves keeps collections and only unassigned shelves', () => {
  const result = topLevelShelves([
    shelf('loose', 'STATIC'),
    shelf('assigned', 'SMART', ['collection-a', 'collection-b']),
    shelf('collection-a', 'COLLECTION')
  ]);

  assert.deepEqual(result.map((item) => item.id), ['loose', 'collection-a']);
});
