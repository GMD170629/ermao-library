import type { MediaKind } from '../../../types/work';

type ReadingStatus = 'UNREAD' | 'READING' | 'FINISHED';
type LibraryProjection = 'bookshelf' | 'management';

export type BookshelfWorkSummary = Readonly<{
  projection: 'bookshelf';
  id: string;
  title: string;
  author: string;
  coverUrl: string;
  availableMediaKinds: MediaKind[];
}>;

export type ManagementWorkSummary = Readonly<{
  projection: 'management';
  id: string;
  title: string;
  author: string;
  gradient: string;
  coverStatus: string;
  coverUrl: string;
  seriesName: string | null;
  tags: string[];
  availableMediaKinds: MediaKind[];
  statusValue: ReadingStatus;
  lastReadAt: string | null;
  importedAt: string | null;
}>;

export type LibraryWorkSummary = BookshelfWorkSummary | ManagementWorkSummary;

export type LibraryWorksPage = Readonly<{
  books: LibraryWorkSummary[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}>;

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`LIBRARY_WORK_SUMMARY_INVALID_${field}`);
  }
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function parseMediaKinds(value: unknown): MediaKind[] {
  if (!Array.isArray(value)) throw new Error('LIBRARY_WORK_SUMMARY_INVALID_availableMediaKinds');
  return value.map((kind) => {
    if (kind === 'EBOOK' || kind === 'COMIC' || kind === 'AUDIOBOOK') return kind;
    throw new Error('LIBRARY_WORK_SUMMARY_INVALID_availableMediaKinds');
  });
}

function mapBookshelfWork(value: unknown): BookshelfWorkSummary {
  const item = record(value);
  return {
    projection: 'bookshelf',
    id: requiredString(item.id, 'id'),
    title: requiredString(item.title, 'title'),
    author: requiredString(item.author, 'author'),
    coverUrl: requiredString(item.coverUrl, 'coverUrl'),
    availableMediaKinds: parseMediaKinds(item.availableMediaKinds)
  };
}

function mapManagementWork(value: unknown): ManagementWorkSummary {
  const item = record(value);
  const statusValue = item.statusValue;
  if (statusValue !== 'UNREAD' && statusValue !== 'READING' && statusValue !== 'FINISHED') {
    throw new Error('LIBRARY_WORK_SUMMARY_INVALID_statusValue');
  }
  return {
    projection: 'management',
    id: requiredString(item.id, 'id'),
    title: requiredString(item.title, 'title'),
    author: requiredString(item.author, 'author'),
    gradient: requiredString(item.gradient, 'gradient'),
    coverStatus: requiredString(item.coverStatus, 'coverStatus'),
    coverUrl: requiredString(item.coverUrl, 'coverUrl'),
    seriesName: optionalString(item.seriesName),
    tags: Array.isArray(item.tags)
      ? item.tags.filter((tag): tag is string => typeof tag === 'string')
      : [],
    availableMediaKinds: parseMediaKinds(item.availableMediaKinds),
    statusValue,
    lastReadAt: optionalString(item.lastReadAt),
    importedAt: optionalString(item.importedAt)
  };
}

export function mapLibraryWorkSummary(
  value: unknown,
  projection: LibraryProjection
): LibraryWorkSummary {
  return projection === 'bookshelf'
    ? mapBookshelfWork(value)
    : mapManagementWork(value);
}

export function libraryWorksUrl(
  queryBase: string,
  page: number,
  pageSize: string,
  projection: LibraryProjection
): string {
  const params = new URLSearchParams(queryBase);
  params.set('page', String(page));
  params.set('pageSize', pageSize);
  params.set('view', projection);
  return `/api/works?${params.toString()}`;
}

export async function fetchLibraryWorksPage(
  queryBase: string,
  page: number,
  pageSize: string,
  projection: LibraryProjection,
  signal?: AbortSignal
): Promise<LibraryWorksPage> {
  const response = await fetch(libraryWorksUrl(queryBase, page, pageSize, projection), {
    cache: 'no-store',
    credentials: 'same-origin',
    signal
  });
  const payload: unknown = await response.json().catch(() => null);
  const envelope = record(payload);
  const error = record(envelope.error);
  if (!response.ok || envelope.ok !== true) {
    throw new Error(typeof error.message === 'string' ? error.message : `LIBRARY_WORKS_REQUEST_FAILED_${response.status}`);
  }
  const data = record(envelope.data);
  if (!Array.isArray(data.books)) throw new Error('LIBRARY_WORKS_CONTRACT_INVALID');
  return {
    books: data.books.map((book) => mapLibraryWorkSummary(book, projection)),
    total: finiteNumber(data.total, 0),
    page: finiteNumber(data.page, page),
    pageSize: finiteNumber(data.pageSize, Number(pageSize)),
    totalPages: finiteNumber(data.totalPages, 1)
  };
}
