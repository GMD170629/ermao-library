import readerHttpErrorStatuses from '../../../../../packages/reader-contracts/reader-http-error-statuses.json';
import { withBasePath } from '../../../lib/base-path';
import {
  parseReaderV5ProgressSnapshot,
  parseReaderV5ProgressWriteResult
} from '../../../lib/reader/v5-wire';
import type {
  ReaderV5ProgressQueryResult,
  ReaderV5ProgressQueryTransport,
  ReaderV5ProgressWriteTransport
} from '../../../lib/reader/v5-sync-coordinator';

export type ReaderResourceStage = 'resource' | 'pdf' | 'comic';

export class ReaderResourceError extends Error {
  readonly source = 'server';

  constructor(readonly code: string, readonly stage: ReaderResourceStage, readonly status: number, options?: ErrorOptions) {
    super(code, options);
    this.name = 'ReaderResourceError';
  }
}

const PUBLICATION_ERROR_STATUSES: Readonly<Record<string, readonly number[]>> = readerHttpErrorStatuses.publication;
const COMIC_ERROR_STATUSES: Readonly<Record<string, readonly number[]>> = readerHttpErrorStatuses.comic;

/** Read only the bounded code header; do not await or expose an error body. */
export async function readerResourceFailure(response: Response, stage: ReaderResourceStage): Promise<ReaderResourceError> {
  const header = response.headers.get('X-Error-Code');
  const code = header && /^[A-Z][A-Z0-9_]{0,63}$/.test(header)
    && (PUBLICATION_ERROR_STATUSES[header] ?? (stage === 'comic' ? COMIC_ERROR_STATUSES[header] : undefined))?.includes(response.status)
    ? header : response.status === 401 ? 'UNAUTHORIZED'
      : response.status === 403 ? 'FORBIDDEN'
        : response.status === 404 || response.status === 410 ? 'PUBLICATION_NOT_FOUND'
          : response.status === 409 || response.status === 412 ? 'PUBLICATION_CHANGED'
            : response.status === 413 ? 'PUBLICATION_RESOURCE_TOO_LARGE'
              : response.status === 429 ? 'RATE_LIMITED'
                : response.status >= 500 ? 'SERVER_UNAVAILABLE' : 'PUBLICATION_RESPONSE_INVALID';
  const failure = new ReaderResourceError(code, stage, response.status);
  try {
    await response.body?.cancel(failure);
  } catch (cause) {
    // A cleanup failure must not replace the already observed HTTP failure.
    return new ReaderResourceError(code, stage, response.status, { cause });
  }
  return failure;
}

/** Reader bytes use authenticated same-origin requests and never enter browser/PWA caches. */
export function requestReaderResource(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const raw = input instanceof Request ? input.url : String(input);
  const url = new URL(withBasePath(raw), window.location.href);
  if (url.origin !== window.location.origin || !url.pathname.includes('/api/')) {
    return Promise.reject(new Error('READER_RESOURCE_URL_INVALID'));
  }
  return fetch(url, { ...init, credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function progressErrorMessage(root: Record<string, unknown>, status: number) {
  const error = objectRecord(root.error);
  return typeof error.message === 'string'
    ? error.message
    : typeof root.detail === 'string' ? root.detail : `阅读进度请求失败（${status}）`;
}

/** The reader feature owns the v5 progress HTTP boundary; runtime only injects these validated transports. */
export const readerV5ProgressTransport: ReaderV5ProgressWriteTransport = async (upload, signal) => {
  const response = await fetch(`/api/reader/v5/resources/${encodeURIComponent(upload.resourceId)}/progress`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    cache: 'no-store',
    signal,
    body: JSON.stringify(upload.request)
  });
  const payload: unknown = await response.json().catch(() => null);
  const root = objectRecord(payload);
  if (!response.ok || root.ok !== true) throw new Error(progressErrorMessage(root, response.status));
  const result = parseReaderV5ProgressWriteResult(objectRecord(root.data));
  if (!result) throw new Error('READER_PROGRESS_RESPONSE_INVALID');
  return result;
};

export const readerV5ProgressQueryTransport: ReaderV5ProgressQueryTransport = async (resourceId, etag, signal) => {
  const response = await fetch(`/api/reader/v5/resources/${encodeURIComponent(resourceId)}/progress`, {
    method: 'GET',
    headers: etag ? { 'If-None-Match': etag } : undefined,
    credentials: 'same-origin',
    cache: 'no-store',
    signal
  });
  const nextEtag = response.headers.get('ETag');
  if (response.status === 304) return { kind: 'unchanged', etag: nextEtag ?? etag } satisfies ReaderV5ProgressQueryResult;
  const payload: unknown = await response.json().catch(() => null);
  const root = objectRecord(payload);
  if (!response.ok || root.ok !== true) throw new Error(progressErrorMessage(root, response.status));
  const data = objectRecord(root.data);
  if (data.schemaVersion !== 5 || !Object.prototype.hasOwnProperty.call(data, 'progressSnapshot')) {
    throw new Error('READER_PROGRESS_RESPONSE_INVALID');
  }
  if (data.progressSnapshot === null) return { kind: 'current', snapshot: null, etag: nextEtag } satisfies ReaderV5ProgressQueryResult;
  const snapshot = parseReaderV5ProgressSnapshot(data.progressSnapshot);
  if (!snapshot) throw new Error('READER_PROGRESS_RESPONSE_INVALID');
  return { kind: 'current', snapshot, etag: nextEtag } satisfies ReaderV5ProgressQueryResult;
};
