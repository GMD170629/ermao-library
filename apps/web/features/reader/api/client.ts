import { withBasePath } from '../../../lib/base-path';

/** Reader bytes use authenticated same-origin requests and never enter browser/PWA caches. */
export function requestReaderResource(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const raw = input instanceof Request ? input.url : String(input);
  const url = new URL(withBasePath(raw), window.location.href);
  if (url.origin !== window.location.origin || !url.pathname.includes('/api/')) {
    return Promise.reject(new Error('READER_RESOURCE_URL_INVALID'));
  }
  return fetch(url, { ...init, credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
}
