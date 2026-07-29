import type { ShelfView } from './types';

export function topLevelShelves(shelves: readonly ShelfView[]): ShelfView[] {
  return shelves.filter(
    (shelf) => shelf.kind === 'COLLECTION' || (shelf.collectionIds?.length ?? 0) === 0
  );
}

