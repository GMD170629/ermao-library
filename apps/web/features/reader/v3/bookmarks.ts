import type { ReaderPositionReport } from '@shuku/reader-core';
import { parseReaderV5PositionReport, readerPositionDigest } from '../../../lib/reader/v5-wire';

export type ReaderBookmark = {
  id: string;
  position: ReaderPositionReport;
  label: string;
  createdAt: string;
};

export function readerBookmarkStorageKey(userId: string, resourceId: string) {
  return ['shuku', 'reader-bookmarks', 'v5', userId, resourceId].join(':');
}

export function readerBookmarkId(position: ReaderPositionReport | null | undefined) {
  const parsed = parseReaderV5PositionReport(position);
  return parsed ? readerPositionDigest(parsed) : null;
}

export function readReaderBookmarks(raw: string | null): ReaderBookmark[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is ReaderBookmark => {
      if (!item || typeof item !== 'object') return false;
      const candidate = item as Partial<ReaderBookmark>;
      const position = parseReaderV5PositionReport(candidate.position);
      return typeof candidate.id === 'string'
        && typeof candidate.label === 'string'
        && typeof candidate.createdAt === 'string'
        && position !== null
        && readerBookmarkId(position) === candidate.id;
    });
  } catch {
    return [];
  }
}

export function mergeReaderBookmarks(...groups: ReaderBookmark[][]) {
  const merged = new Map<string, ReaderBookmark>();
  groups.flat().forEach((bookmark) => {
    const existing = merged.get(bookmark.id);
    if (!existing || bookmark.createdAt > existing.createdAt) merged.set(bookmark.id, bookmark);
  });
  return [...merged.values()].sort((left, right) => (
    left.position.presentation.displayPercent - right.position.presentation.displayPercent
    || left.createdAt.localeCompare(right.createdAt)
  ));
}

export function toggleReaderBookmark(bookmarks: ReaderBookmark[], next: Omit<ReaderBookmark, 'id'>) {
  const id = readerBookmarkId(next.position);
  if (!id) return bookmarks;
  if (bookmarks.some((bookmark) => bookmark.id === id)) {
    return bookmarks.filter((bookmark) => bookmark.id !== id);
  }
  return [...bookmarks, { ...next, id }];
}

export function hasReaderBookmark(bookmarks: ReaderBookmark[], position: ReaderPositionReport | null | undefined) {
  const id = readerBookmarkId(position);
  return Boolean(id && bookmarks.some((bookmark) => bookmark.id === id));
}

export function removeReaderBookmark(bookmarks: ReaderBookmark[], id: string) {
  return bookmarks.filter((bookmark) => bookmark.id !== id);
}
