import readerHttpErrorStatuses from '../../../../../packages/reader-contracts/reader-http-error-statuses.json';
import { withBasePath } from '../../../lib/base-path';

export type ReaderResourceStage = 'manifest' | 'positions' | 'chapter' | 'resource' | 'pdf' | 'comic';

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
