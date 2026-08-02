import type { ReflowableFormat } from '@shuku/reader-core';
import { sanitizeEpubMarkup } from './epub-security';
import { decodeTxt, makeTxtBook } from './txt-book';

export type FoliateSection = {
  id?: unknown;
  size?: number;
  load: () => string | Promise<string>;
  unload?: () => void;
  createDocument?: () => Document | Promise<Document>;
};

export type FoliateTocItem = {
  id?: unknown;
  label?: unknown;
  href?: unknown;
  subitems?: unknown;
  navigationKey?: unknown;
};

export type FoliateBook = {
  sections: FoliateSection[];
  toc?: FoliateTocItem[];
  dir?: unknown;
  metadata?: unknown;
  transformTarget?: EventTarget;
  resolveHref?: (href: string) => unknown | Promise<unknown>;
  splitTOCHref?: (href: string) => unknown;
  destroy?: () => void | Promise<void>;
};

export type OpenFoliateBookOptions = {
  url: string;
  format: ReflowableFormat;
  title: string;
  signal: AbortSignal;
  fetch?: typeof globalThis.fetch;
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

export async function openFoliateBook(options: OpenFoliateBookOptions) {
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
  const blob = await response.blob();
  if (options.signal.aborted) throw new DOMException('The operation was aborted', 'AbortError');
  if (!blob.size) throw new NovelOpenError('NOVEL_RESOURCE_FAILED', 'The book file is empty');

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
