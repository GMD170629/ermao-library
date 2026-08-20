export type LibraryBatchAction =
  | 'metadata'
  | 'find_replace'
  | 'shelves'
  | 'reading_status'
  | 'covers';

const personalLibraryBatchActions = new Set<LibraryBatchAction>([
  'shelves',
  'reading_status'
]);

export function canUseLibraryBatchAction(
  action: LibraryBatchAction,
  canManageSystem: boolean
) {
  return canManageSystem || personalLibraryBatchActions.has(action);
}
