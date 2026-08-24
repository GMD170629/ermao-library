import type { BookView, ReadableResourceView } from '../../../types/book';

export type BookReadingStatus = 'UNREAD' | 'READING' | 'FINISHED';

export type BookActionId =
  | 'edit'
  | 'regenerate-image'
  | 'reading-status'
  | 'recognize'
  | 'rescan'
  | 'delete';

export function bookActionIds(canManage: boolean): BookActionId[] {
  return canManage
    ? ['edit', 'regenerate-image', 'reading-status', 'recognize', 'rescan', 'delete']
    : ['reading-status'];
}

export function nextBookReadingStatus(status: BookReadingStatus): 'UNREAD' | 'FINISHED' {
  return status === 'FINISHED' ? 'UNREAD' : 'FINISHED';
}

export function bookReadingStatus(book: Pick<BookView, 'completed' | 'resources'>): BookReadingStatus {
  if (book.completed) return 'FINISHED';
  return book.resources.some((resource) => !resource.hidden && resource.progress > 0)
    ? 'READING'
    : 'UNREAD';
}

export function resumeResourceForBook(book: BookView): ReadableResourceView | null {
  const resources = book.resources.filter((resource) => !resource.hidden && resource.readable);
  return resources.find((resource) => resource.id === book.continueResourceId)
    ?? resources.find((resource) => resource.progress < 100)
    ?? resources[0]
    ?? null;
}
