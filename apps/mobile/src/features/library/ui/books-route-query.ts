import {
  normalizeBooksQuery,
  type BooksQuery,
  type LibraryMediaKind,
  type LibraryReadingStatus,
  type LibrarySort,
  type LibrarySortDirection,
  type LibraryView,
} from '../model/library';

export type BooksRouteParameters = Readonly<{
  direction?: string | readonly string[] | undefined;
  mediaKind?: string | readonly string[] | undefined;
  search?: string | readonly string[] | undefined;
  shelfId?: string | readonly string[] | undefined;
  sort?: string | readonly string[] | undefined;
  status?: string | readonly string[] | undefined;
  view?: string | readonly string[] | undefined;
}>;

export type EncodedBooksRouteParameters = Readonly<{
  direction: string;
  mediaKind: string;
  search: string;
  shelfId: string;
  sort: string;
  status: string;
  view: string;
}>;

const READING_STATUSES: readonly LibraryReadingStatus[] = [
  'FINISHED',
  'READING',
  'UNREAD',
];
const MEDIA_KINDS: readonly LibraryMediaKind[] = [
  'AUDIOBOOK',
  'COMIC',
  'EBOOK',
];
const SORTS: readonly LibrarySort[] = [
  'author',
  'recent_import',
  'recent_read',
  'series',
  'title',
];
const DIRECTIONS: readonly LibrarySortDirection[] = ['asc', 'desc'];
const VIEWS: readonly LibraryView[] = ['grid', 'list'];

export function decodeBooksRouteQuery(
  parameters: BooksRouteParameters,
  fallback: BooksQuery,
): BooksQuery {
  return normalizeBooksQuery({
    search: readParameter(parameters.search) ?? fallback.search,
    status: readNullableEnum(
      parameters.status,
      READING_STATUSES,
      fallback.status,
    ),
    mediaKind: readNullableEnum(
      parameters.mediaKind,
      MEDIA_KINDS,
      fallback.mediaKind,
    ),
    sort: readEnum(parameters.sort, SORTS, fallback.sort),
    direction: readEnum(
      parameters.direction,
      DIRECTIONS,
      fallback.direction,
    ),
    view: readEnum(parameters.view, VIEWS, fallback.view),
    shelfId: readNullableString(parameters.shelfId, fallback.shelfId),
  });
}

export function encodeBooksRouteQuery(
  query: BooksQuery,
): EncodedBooksRouteParameters {
  const normalized = normalizeBooksQuery(query);
  return {
    search: normalized.search,
    status: normalized.status ?? '',
    mediaKind: normalized.mediaKind ?? '',
    sort: normalized.sort,
    direction: normalized.direction,
    view: normalized.view,
    shelfId: normalized.shelfId ?? '',
  };
}

export function booksQueriesMatch(
  left: BooksQuery,
  right: BooksQuery,
): boolean {
  return (
    left.search === right.search &&
    left.status === right.status &&
    left.mediaKind === right.mediaKind &&
    left.sort === right.sort &&
    left.direction === right.direction &&
    left.view === right.view &&
    left.shelfId === right.shelfId
  );
}

export function booksRouteParametersMatch(
  current: BooksRouteParameters,
  expected: EncodedBooksRouteParameters,
): boolean {
  return (
    readParameter(current.search) === expected.search &&
    readParameter(current.status) === expected.status &&
    readParameter(current.mediaKind) === expected.mediaKind &&
    readParameter(current.sort) === expected.sort &&
    readParameter(current.direction) === expected.direction &&
    readParameter(current.view) === expected.view &&
    readParameter(current.shelfId) === expected.shelfId
  );
}

function readParameter(
  parameter: string | readonly string[] | undefined,
): string | undefined {
  if (typeof parameter === 'string' || parameter === undefined) {
    return parameter;
  }
  return parameter[0];
}

function readNullableString(
  parameter: string | readonly string[] | undefined,
  fallback: string | null,
): string | null {
  const value = readParameter(parameter);
  if (value === undefined) return fallback;
  const normalized = value.trim();
  if (normalized.length === 0) return null;
  return normalized.length > 191 ? fallback : normalized;
}

function readNullableEnum<Value extends string>(
  parameter: string | readonly string[] | undefined,
  values: readonly Value[],
  fallback: Value | null,
): Value | null {
  const value = readParameter(parameter);
  if (value === undefined) return fallback;
  if (value.length === 0) return null;
  return values.find((candidate) => candidate === value) ?? fallback;
}

function readEnum<Value extends string>(
  parameter: string | readonly string[] | undefined,
  values: readonly Value[],
  fallback: Value,
): Value {
  const value = readParameter(parameter);
  return values.find((candidate) => candidate === value) ?? fallback;
}
