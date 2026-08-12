import type { ReflowableFormat } from '@shuku/reader-core';
import {
  readerBookCacheKey,
  readerBookUserVolumeKey,
  type ReaderBookCache,
  type ReaderBookCacheIdentity
} from '../../../../lib/reader/book-cache';
import { sanitizeEpubMarkup } from './epub-security';
import { decodeTxt, makeTxtBook } from './txt-book';

export type FoliateSection = {
  id?: unknown;
  cfi?: unknown;
  linear?: unknown;
  size?: number;
  load: () => string | Promise<string>;
  unload?: () => void;
  createDocument?: () => Document | Promise<Document>;
  resolveHref?: (href: string) => unknown;
};

export type FoliateTocItem = {
  id?: unknown;
  label?: unknown;
  href?: unknown;
  subitems?: unknown;
  navigationKey?: unknown;
};

export type FoliateRendition = {
  layout?: unknown;
  viewport?: unknown;
};

export type FoliateBook = {
  sections: FoliateSection[];
  toc?: FoliateTocItem[];
  dir?: unknown;
  metadata?: unknown;
  rendition?: FoliateRendition;
  transformTarget?: EventTarget;
  resolveHref?: (href: string) => unknown | Promise<unknown>;
  resolveCFI?: (cfi: string) => unknown;
  splitTOCHref?: (href: string) => unknown;
  destroy?: () => void | Promise<void>;
};

export type OpenFoliateBookOptions = {
  url: string;
  format: ReflowableFormat;
  title: string;
  signal: AbortSignal;
  expectedSha256?: string;
  fetch?: typeof globalThis.fetch;
  cache?: {
    storage: ReaderBookCache;
    identity: ReaderBookCacheIdentity;
  };
  onDownloadProgress?: (progress: FoliateDownloadProgress) => void;
  onPhase?: (phase: 'downloading' | 'parsing') => void;
  onCacheWarning?: (code: 'BOOK_CACHE_WRITE_FAILED') => void;
};

async function sha256(blob: Blob) {
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return `sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

async function requireExpectedHash(blob: Blob, expectedSha256: string | undefined) {
  if (!expectedSha256) return;
  if (!/^sha256:[0-9a-f]{64}$/iu.test(expectedSha256)) {
    throw new NovelOpenError('NOVEL_RESOURCE_FAILED', 'The publication hash is invalid');
  }
  if ((await sha256(blob)).toLowerCase() !== expectedSha256.toLowerCase()) {
    throw new NovelOpenError('NOVEL_RESOURCE_FAILED', 'The publication hash does not match');
  }
}

export type FoliateDownloadProgress = {
  loadedBytes: number;
  totalBytes: number | null;
  percent: number | null;
};

export class NovelOpenError extends Error {
  constructor(
    readonly code:
      | 'NOVEL_UNSUPPORTED_FORMAT'
      | 'NOVEL_DRM_PROTECTED'
      | 'NOVEL_PARSE_FAILED'
      | 'NOVEL_ENCODING_UNCERTAIN'
      | 'NOVEL_RESOURCE_FAILED'
      | 'NOVEL_SECURITY_REJECTED',
    message: string,
    options?: ErrorOptions
  ) {
    super(message, options);
    this.name = 'NovelOpenError';
  }
}

const mimeByFormat: Record<ReflowableFormat, string> = {
  epub: 'application/epub+zip',
  mobi: 'application/x-mobipocket-ebook',
  azw: 'application/vnd.amazon.ebook',
  azw3: 'application/vnd.amazon.ebook',
  prc: 'application/x-mobipocket-ebook',
  fb2: 'application/x-fictionbook+xml',
  txt: 'text/plain'
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function positiveDimension(value: unknown): boolean {
  if (typeof value !== 'string' && typeof value !== 'number') return false;
  const parsed = typeof value === 'number' ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed > 0;
}

function hasFixedLayoutViewportDimensions(value: unknown): boolean {
  if (isRecord(value)) {
    return positiveDimension(value.width) && positiveDimension(value.height);
  }
  if (typeof value !== 'string') return false;
  const dimensions = Object.fromEntries(value
    .split(/[,;\s]/u)
    .filter(Boolean)
    .map((part) => part.split('=').map((token) => token.trim()))
    .filter((entry): entry is [string, string] => entry.length === 2));
  return positiveDimension(dimensions.width) && positiveDimension(dimensions.height);
}

export function normalizeFoliateFixedLayoutViewport(book: FoliateBook): void {
  const rendition = book.rendition;
  if (!rendition || rendition.layout !== 'pre-paginated') return;
  if (hasFixedLayoutViewportDimensions(rendition.viewport)) return;

  // Foliate treats any viewport object, including an empty one, as authoritative.
  // Removing invalid dimensions lets its fixed-layout renderer use the loaded
  // page image's natural size instead of leaving the iframe at 300 x 150.
  book.rendition = { ...rendition, viewport: undefined };
}

function isFoliateBook(value: unknown): value is FoliateBook {
  return isRecord(value)
    && Array.isArray(value.sections)
    && value.sections.length > 0
    && value.sections.every((section) => isRecord(section) && typeof section.load === 'function');
}

function isMarkup(type: unknown, value: unknown) {
  if (typeof type === 'string' && /(?:xhtml|html|xml)/i.test(type)) return true;
  return typeof value === 'string' && /^\s*(?:<\?xml[^>]*>\s*)?<html\b/i.test(value);
}

async function sanitizeTransformData(value: unknown, type: unknown) {
  const resolved = await value;
  if (!isMarkup(type, resolved)) return resolved;
  if (typeof resolved === 'string') return sanitizeEpubMarkup(resolved);
  if (resolved instanceof Blob) {
    return new Blob([sanitizeEpubMarkup(await resolved.text())], {
      type: typeof type === 'string' ? type : resolved.type || 'application/xhtml+xml'
    });
  }
  throw new NovelOpenError('NOVEL_SECURITY_REJECTED', 'The book markup could not be sanitized');
}

function installTransformSecurity(book: FoliateBook) {
  if (!book.transformTarget) return () => undefined;
  const controller = new AbortController();
  book.transformTarget.addEventListener('data', (event) => {
    const detail = event instanceof CustomEvent ? event.detail : null;
    if (!isRecord(detail) || !('data' in detail)) {
      throw new NovelOpenError('NOVEL_SECURITY_REJECTED', 'The book transform event was invalid');
    }
    detail.data = sanitizeTransformData(detail.data, detail.type);
  }, { signal: controller.signal });
  return () => controller.abort();
}

function classifyOpenError(reason: unknown) {
  if (reason instanceof NovelOpenError) return reason;
  if (reason instanceof DOMException && reason.name === 'AbortError') return reason;
  const message = reason instanceof Error ? reason.message : '';
  if (/drm|encrypted|encryption|protected/i.test(message)) {
    return new NovelOpenError('NOVEL_DRM_PROTECTED', 'This book is DRM protected', { cause: reason });
  }
  if (/unsupported|type not supported/i.test(message)) {
    return new NovelOpenError('NOVEL_UNSUPPORTED_FORMAT', 'The book format is not supported', { cause: reason });
  }
  return new NovelOpenError('NOVEL_PARSE_FAILED', 'The book could not be parsed', { cause: reason });
}

const localBookLocks = new Map<string, Promise<void>>();

async function withLocalBookLock<T>(key: string, action: () => Promise<T>): Promise<T> {
  const previous = localBookLocks.get(key) ?? Promise.resolve();
  let release: () => void = () => undefined;
  const current = new Promise<void>((resolve) => {
    release = resolve;
  });
  const queued = previous.then(() => current);
  localBookLocks.set(key, queued);
  await previous;
  try {
    return await action();
  } finally {
    release();
    if (localBookLocks.get(key) === queued) localBookLocks.delete(key);
  }
}

async function withBookLock<T>(key: string, action: () => Promise<T>): Promise<T> {
  const execute = () => withLocalBookLock(key, action);
  if (typeof navigator !== 'undefined' && navigator.locks) {
    return navigator.locks.request(`shuku-reader-book:${key}`, execute);
  }
  return execute();
}

function contentLength(response: Response) {
  const value = Number.parseInt(response.headers.get('content-length') ?? '', 10);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function emitDownloadProgress(
  callback: OpenFoliateBookOptions['onDownloadProgress'],
  loadedBytes: number,
  totalBytes: number | null
) {
  callback?.({
    loadedBytes,
    totalBytes,
    percent: totalBytes === null ? null : Math.min(100, loadedBytes / totalBytes * 100)
  });
}

async function responseBlobWithProgress(
  response: Response,
  signal: AbortSignal,
  callback: OpenFoliateBookOptions['onDownloadProgress']
) {
  const totalBytes = contentLength(response);
  emitDownloadProgress(callback, 0, totalBytes);
  if (!response.body) {
    const blob = await response.blob();
    emitDownloadProgress(callback, blob.size, totalBytes ?? blob.size);
    return blob;
  }

  const reader = response.body.getReader();
  const chunks: ArrayBuffer[] = [];
  let loadedBytes = 0;
  try {
    while (true) {
      if (signal.aborted) throw new DOMException('The operation was aborted', 'AbortError');
      const { done, value } = await reader.read();
      if (done) break;
      if (!value?.byteLength) continue;
      const chunk = new Uint8Array(value.byteLength);
      chunk.set(value);
      chunks.push(chunk.buffer);
      loadedBytes += value.byteLength;
      emitDownloadProgress(callback, loadedBytes, totalBytes);
    }
  } catch (reason) {
    await reader.cancel(reason).catch(() => undefined);
    throw reason;
  } finally {
    reader.releaseLock();
  }
  const blob = new Blob(chunks, { type: response.headers.get('content-type') ?? '' });
  emitDownloadProgress(callback, blob.size, totalBytes ?? blob.size);
  return blob;
}

async function downloadBookBlob(options: OpenFoliateBookOptions) {
  options.onPhase?.('downloading');
  const fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  let response: Response;
  try {
    response = await fetcher(options.url, {
      credentials: 'same-origin',
      cache: 'no-store',
      signal: options.signal
    });
  } catch (reason) {
    if (options.signal.aborted) throw reason;
    throw new NovelOpenError('NOVEL_RESOURCE_FAILED', 'The book file could not be downloaded', { cause: reason });
  }
  if (!response.ok) {
    throw new NovelOpenError('NOVEL_RESOURCE_FAILED', `The book file request failed (${response.status})`);
  }
  const blob = await responseBlobWithProgress(response, options.signal, options.onDownloadProgress);
  if (options.signal.aborted) throw new DOMException('The operation was aborted', 'AbortError');
  if (!blob.size) throw new NovelOpenError('NOVEL_RESOURCE_FAILED', 'The book file is empty');
  return blob;
}

async function parseBookBlob(options: OpenFoliateBookOptions, blob: Blob) {
  options.onPhase?.('parsing');
  if (options.format === 'txt') {
    try {
      const book = makeTxtBook(decodeTxt(await blob.arrayBuffer()), options.title);
      return { book, destroy: () => book.destroy() };
    } catch (reason) {
      if (isRecord(reason) && reason.code === 'NOVEL_ENCODING_UNCERTAIN') {
        throw new NovelOpenError('NOVEL_ENCODING_UNCERTAIN', 'The TXT encoding could not be determined', { cause: reason });
      }
      throw classifyOpenError(reason);
    }
  }

  try {
    const foliateView = await import('foliate-js/view.js');
    const file = new File([blob], `book.${options.format}`, {
      type: mimeByFormat[options.format] || blob.type,
      lastModified: 0
    });
    const candidate: unknown = await foliateView.makeBook(file);
    if (!isFoliateBook(candidate)) {
      throw new NovelOpenError('NOVEL_PARSE_FAILED', 'The parser returned an invalid book');
    }
    normalizeFoliateFixedLayoutViewport(candidate);
    const removeSecurityTransform = installTransformSecurity(candidate);
    let destroyed = false;
    return {
      book: candidate,
      destroy: async () => {
        if (destroyed) return;
        destroyed = true;
        removeSecurityTransform();
        await candidate.destroy?.();
      }
    };
  } catch (reason) {
    throw classifyOpenError(reason);
  }
}

async function persistBookBlob(options: OpenFoliateBookOptions, blob: Blob) {
  if (!options.cache) return;
  const { identity, storage } = options.cache;
  try {
    await storage.putBookFile({
      ...identity,
      key: readerBookCacheKey(identity),
      userVolumeKey: readerBookUserVolumeKey(identity),
      format: options.format,
      mimeType: blob.type || mimeByFormat[options.format],
      sizeBytes: blob.size,
      blob,
      createdAt: Date.now()
    });
    if (typeof navigator !== 'undefined' && navigator.storage?.persist) {
      void navigator.storage.persist().catch(() => undefined);
    }
  } catch {
    options.onCacheWarning?.('BOOK_CACHE_WRITE_FAILED');
  }
}

async function openFoliateBookLocked(options: OpenFoliateBookOptions) {
  const cached = await options.cache?.storage.getBookFile(options.cache.identity).catch(() => null);
  if (cached && cached.format === options.format && cached.blob.size === cached.sizeBytes) {
    try {
      await requireExpectedHash(cached.blob, options.expectedSha256);
      return await parseBookBlob(options, cached.blob);
    } catch (reason) {
      if (options.signal.aborted) throw reason;
      await options.cache?.storage.deleteBookFile(options.cache.identity).catch(() => undefined);
    }
  }

  const blob = await downloadBookBlob(options);
  await requireExpectedHash(blob, options.expectedSha256);
  const opened = await parseBookBlob(options, blob);
  await persistBookBlob(options, blob);
  return opened;
}

export async function openFoliateBook(options: OpenFoliateBookOptions) {
  if (!options.cache) return openFoliateBookLocked(options);
  return withBookLock(readerBookCacheKey(options.cache.identity), () => openFoliateBookLocked(options));
}
