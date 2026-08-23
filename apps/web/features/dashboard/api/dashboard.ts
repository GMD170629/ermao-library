import type { BookshelfItem } from '../../../components/book/bookshelf';
import type { MediaKind } from '../../../types/book';
import { mapContinueReadingItem, type ContinueReadingItem } from '../model/continue-reading';

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`Invalid dashboard field: ${field}`);
  return value;
}

function mediaKinds(value: unknown): MediaKind[] {
  if (!Array.isArray(value)) throw new Error('Invalid dashboard field: availableMediaKinds');
  return value.filter((kind): kind is MediaKind => (
    kind === 'EBOOK' || kind === 'COMIC' || kind === 'AUDIOBOOK'
  ));
}

function parseBook(value: unknown): BookshelfItem {
  if (!isObject(value)) throw new Error('Invalid dashboard book');
  if (typeof value.progress !== 'number' || !Number.isFinite(value.progress)) {
    throw new Error('Invalid dashboard field: progress');
  }
  return {
    id: requiredString(value.id, 'book.id'),
    title: requiredString(value.title, 'book.title'),
    author: value.author === null ? null : requiredString(value.author, 'book.author'),
    coverUrl: requiredString(value.coverUrl, 'book.coverUrl'),
    availableMediaKinds: mediaKinds(value.availableMediaKinds),
    progress: Math.max(0, Math.min(100, value.progress))
  };
}

async function readData(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(path, {
    cache: 'no-store',
    credentials: 'same-origin',
    signal
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok || !isObject(payload) || payload.ok !== true || !('data' in payload)) {
    const message = isObject(payload) && isObject(payload.error) && typeof payload.error.message === 'string'
      ? payload.error.message
      : '读取数据失败';
    throw new Error(message);
  }
  return payload.data;
}

async function fetchBooks(path: string, signal?: AbortSignal): Promise<BookshelfItem[]> {
  const data = await readData(path, signal);
  if (!isObject(data) || !Array.isArray(data.books)) {
    throw new Error('Invalid dashboard books response');
  }
  return data.books.map(parseBook);
}

export async function fetchDashboardContinueReading(
  signal?: AbortSignal
): Promise<ContinueReadingItem | null> {
  const data = await readData('/api/dashboard/continue-reading', signal);
  if (!isObject(data) || !('item' in data)) {
    throw new Error('Invalid continue-reading response');
  }
  return mapContinueReadingItem(data.item);
}

export function fetchDashboardRecentReading(signal?: AbortSignal): Promise<BookshelfItem[]> {
  return fetchBooks('/api/dashboard/recent-reading?limit=10', signal);
}

export function fetchDashboardRecentBooks(signal?: AbortSignal): Promise<BookshelfItem[]> {
  return fetchBooks('/api/dashboard/recent-books?limit=10', signal);
}
