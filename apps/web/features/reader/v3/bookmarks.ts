import type { ReaderLocation } from '@shuku/reader-core';

export type ReaderBookmark = {
  id: string;
  location: ReaderLocation;
  label: string;
  percent: number;
  createdAt: string;
};

export function readerBookmarkStorageKey(userId: string, volumeId: string) {
  return ['shuku', 'reader-bookmarks', 'v4', userId, volumeId].join(':');
}

export function readerBookmarkId(location: ReaderLocation | null | undefined) {
  if (!location) return null;
  if (location.kind === 'comic') return `comic:${location.volumeId}:${location.pageIndex}`;
  if (location.kind === 'pdf') return `pdf:${location.pageIndex}`;
  if (location.kind === 'reflowable') {
    if (location.cfi) return `reflowable:${location.format}:cfi:${location.cfi}`;
    const progression = typeof location.progression === 'number'
      ? Math.round(location.progression * 10_000) / 10_000
      : '';
    if (location.href || progression !== '') {
      return `reflowable:${location.format}:position:${location.href ?? ''}:${progression}`;
    }
    return null;
  }
  if (location.cfi) return `epub:cfi:${location.cfi}`;

  const progression = typeof location.progression === 'number'
    ? Math.round(location.progression * 10_000) / 10_000
    : '';
  if (location.href || location.spineIndex !== undefined || progression !== '') {
    return `epub:position:${location.href ?? ''}:${location.spineIndex ?? ''}:${progression}`;
  }
  return null;
}

export function readReaderBookmarks(raw: string | null): ReaderBookmark[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is ReaderBookmark => {
      if (!item || typeof item !== 'object') return false;
      const candidate = item as Partial<ReaderBookmark>;
      return typeof candidate.id === 'string'
        && typeof candidate.label === 'string'
        && typeof candidate.percent === 'number'
        && Number.isFinite(candidate.percent)
        && typeof candidate.createdAt === 'string'
        && readerBookmarkId(candidate.location) === candidate.id;
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
  return [...merged.values()].sort((left, right) => left.percent - right.percent || left.createdAt.localeCompare(right.createdAt));
}

export function toggleReaderBookmark(bookmarks: ReaderBookmark[], next: Omit<ReaderBookmark, 'id'>) {
  const id = readerBookmarkId(next.location);
  if (!id) return bookmarks;
  if (bookmarks.some((bookmark) => bookmark.id === id)) {
    return bookmarks.filter((bookmark) => bookmark.id !== id);
  }
  return [...bookmarks, { ...next, id }];
}

export function hasReaderBookmark(bookmarks: ReaderBookmark[], location: ReaderLocation | null | undefined) {
  const id = readerBookmarkId(location);
  return Boolean(id && bookmarks.some((bookmark) => bookmark.id === id));
}

export function removeReaderBookmark(bookmarks: ReaderBookmark[], id: string) {
  return bookmarks.filter((bookmark) => bookmark.id !== id);
}
