import type { MediaKind, ReaderType } from '../../../types/book';

export type ContinueReadingItem = Readonly<{
  bookId: string;
  title: string;
  author: string;
  coverUrl: string;
  mediaKind: MediaKind;
  resourceFormat: string;
  readerType: ReaderType;
  resumeResourceId: string | null;
  progress: number;
  lastReadAt: string | null;
  chapter: string | null;
  resourceTitle: string | null;
  narrator: string | null;
}>;

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function mediaKind(value: unknown): MediaKind | null {
  return value === 'EBOOK' || value === 'COMIC' || value === 'AUDIOBOOK' ? value : null;
}

function readerType(value: unknown): ReaderType | null {
  return value === 'reflowable' || value === 'comic' || value === 'pdf' || value === 'audio' ? value : null;
}

export function mapContinueReadingItem(value: unknown): ContinueReadingItem | null {
  if (value === null) return null;
  const item = record(value);
  const bookId = stringValue(item.bookId).trim();
  const kind = mediaKind(item.mediaKind);
  const reader = readerType(item.readerType);
  if (!bookId || !kind || !reader) return null;
  const progress = typeof item.progress === 'number' && Number.isFinite(item.progress)
    ? Math.max(0, Math.min(100, item.progress))
    : 0;
  return {
    bookId,
    title: stringValue(item.title),
    author: stringValue(item.author),
    coverUrl: stringValue(item.coverUrl),
    mediaKind: kind,
    resourceFormat: stringValue(item.resourceFormat),
    readerType: reader,
    resumeResourceId: nullableString(item.resumeResourceId),
    progress,
    lastReadAt: nullableString(item.lastReadAt),
    chapter: nullableString(item.chapter),
    resourceTitle: nullableString(item.resourceTitle),
    narrator: nullableString(item.narrator)
  };
}
