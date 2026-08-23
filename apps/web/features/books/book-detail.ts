import type { MediaKind, ReadableResourceView, BookView } from '../../types/book';

export function bookDetailReturnHref(value: unknown): string {
  if (typeof value !== 'string' || (!value.startsWith('/library?') && value !== '/library')) {
    return '/library';
  }
  try {
    const url = new URL(value, 'https://local.invalid');
    if (url.origin !== 'https://local.invalid' || url.pathname !== '/library') return '/library';
    return `${url.pathname}${url.search}`;
  } catch {
    return '/library';
  }
}

export function bookDetailHref(
  bookId: string,
  resourceId?: string | null,
  returnTo?: string | null,
  resourcePage?: number | null
): string {
  const query = new URLSearchParams();
  if (resourceId) {
    query.set('resourceId', resourceId);
    if (resourcePage !== null && resourcePage !== undefined) query.set('resourcePage', String(Math.max(1, Math.floor(resourcePage))));
  }
  if (returnTo) query.set('returnTo', bookDetailReturnHref(returnTo));
  const suffix = query.size > 0 ? `?${query}` : '';
  return `/books/${encodeURIComponent(bookId)}${suffix}`;
}

export function resourcePageFromQuery(value: unknown): number {
  if (typeof value !== 'string') return 1;
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
}

export function displayResourceNumber(resource: ReadableResourceView, position: number): number {
  return resource.resourceIndex ?? position + 1;
}

export function formatDuration(durationMs: number | null | undefined): string {
  if (!durationMs || durationMs <= 0) return '';
  const totalSeconds = Math.round(durationMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export function selectedResourceForBook(book: BookView, requestedResourceId?: string | null): ReadableResourceView | null {
  const resources = allVisibleResources(book);
  return resources.find((resource) => resource.id === requestedResourceId)
    ?? resources.find((resource) => resource.id === book.continueResourceId)
    ?? resources.find((resource) => resource.progress <= 0)
    ?? resources[0]
    ?? null;
}

export function allVisibleResources(book: BookView): ReadableResourceView[] {
  return book.resources.filter((resource) => !resource.hidden);
}

export function singleReadableResourceForBook(book: BookView): ReadableResourceView | null {
  const readableResources = allVisibleResources(book).filter((resource) => resource.readable);
  return readableResources.length === 1 ? readableResources[0] ?? null : null;
}

export function mediaKindOfResource(resource: ReadableResourceView): MediaKind {
  if (resource.classification.suggestedMediaKind) return resource.classification.suggestedMediaKind;
  if (resource.readerType === 'audio') return 'AUDIOBOOK';
  if (resource.readerType === 'comic') return 'COMIC';
  return 'EBOOK';
}
