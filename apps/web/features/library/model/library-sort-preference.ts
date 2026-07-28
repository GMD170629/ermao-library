export const LIBRARY_SORTS = [
  'recent_read',
  'recent_import',
  'title',
  'author',
  'publisher',
  'series'
] as const;

export type LibrarySort = (typeof LIBRARY_SORTS)[number];
export type LibrarySortDirection = 'asc' | 'desc';

export type LibrarySortPreference = {
  sort: LibrarySort;
  direction: LibrarySortDirection;
};

export const DEFAULT_LIBRARY_SORT_PREFERENCE: LibrarySortPreference = {
  sort: 'recent_import',
  direction: 'desc'
};

const validLibrarySorts = new Set<string>(LIBRARY_SORTS);

export function isLibrarySort(value: unknown): value is LibrarySort {
  return typeof value === 'string' && validLibrarySorts.has(value);
}

export function isLibrarySortDirection(value: unknown): value is LibrarySortDirection {
  return value === 'asc' || value === 'desc';
}

export function defaultLibrarySortDirection(sort: LibrarySort): LibrarySortDirection {
  return sort === 'recent_read' || sort === 'recent_import' ? 'desc' : 'asc';
}

export function parseLibrarySortPreference(
  sort: unknown,
  direction: unknown
): LibrarySortPreference | null {
  if (!isLibrarySort(sort)) return null;
  return {
    sort,
    direction: isLibrarySortDirection(direction)
      ? direction
      : defaultLibrarySortDirection(sort)
  };
}

export function parseLibrarySortPreferenceValue(value: unknown): LibrarySortPreference | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const candidate = value as { sort?: unknown; direction?: unknown };
  return parseLibrarySortPreference(candidate.sort, candidate.direction);
}

export function librarySortPreferenceFromRoute(
  sort: string | null,
  direction: string | null
): LibrarySortPreference | null {
  if (sort === null && direction === null) return null;
  const resolvedSort = isLibrarySort(sort)
    ? sort
    : DEFAULT_LIBRARY_SORT_PREFERENCE.sort;
  return {
    sort: resolvedSort,
    direction: isLibrarySortDirection(direction)
      ? direction
      : defaultLibrarySortDirection(resolvedSort)
  };
}

export function resolveLibrarySortPreference({
  route,
  account,
  device
}: {
  route: LibrarySortPreference | null;
  account: LibrarySortPreference | null;
  device: LibrarySortPreference | null;
}): LibrarySortPreference {
  return route ?? account ?? device ?? DEFAULT_LIBRARY_SORT_PREFERENCE;
}
