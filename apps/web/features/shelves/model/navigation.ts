import type { ShelfNavigationItem } from './types';

export function topLevelShelves<T extends ShelfNavigationItem>(shelves: readonly T[]): T[] {
  return shelves.filter(
    (shelf) => shelf.kind === 'COLLECTION' || (shelf.collectionIds?.length ?? 0) === 0
  );
}

