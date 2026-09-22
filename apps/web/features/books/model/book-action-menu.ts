import type { BookView, ReadableResourceView } from '../../../types/book';

export type BookReadingStatus = 'UNREAD' | 'READING' | 'FINISHED';

export type BookActionId =
  | 'edit'
  | 'regenerate-image'
  | 'reading-status'
  | 'add-to-shelf'
  | 'download'
  | 'recognize'
  | 'rescan'
  | 'kindle'
  | 'delete';

export function bookActionIds(canManage: boolean, kindleSendAvailable = false): BookActionId[] {
  return [
    ...(canManage ? ['edit', 'regenerate-image'] as const : []),
    'reading-status',
    'add-to-shelf',
    'download',
    ...(kindleSendAvailable ? ['kindle'] as const : []),
    ...(canManage ? ['recognize', 'rescan', 'delete'] as const : [])
  ];
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
