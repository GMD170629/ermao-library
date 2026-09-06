import type { OriginalDownloadTransport } from '../browser-publication-store';
import { requestReaderResource } from '../../../api/client';
import { withBasePath } from '../../../../../lib/base-path';

/** Shared authenticated transport for the complete original-file transfer. */
export const requestOriginalDownload: OriginalDownloadTransport = (descriptor, signal) => requestReaderResource(
  descriptor.downloadUrl,
  {
    method: 'GET',
    credentials: 'same-origin',
    headers: { 'X-Asset-Version': descriptor.assetVersion },
    signal
  }
);

/**
 * Shared same-origin transport for build-time reader artifacts.
 *
 * These files are static publication infrastructure rather than reader API
 * resources, so they deliberately use their own allowlisted transport instead
 * of weakening requestReaderResource's `/api/` boundary.
 */
export function requestReaderArtifact(path: string, init?: RequestInit): Promise<Response> {
  const url = new URL(withBasePath(path), globalThis.location.href);
  const vendorRoot = new URL(withBasePath('/vendor/'), globalThis.location.href);
  if (url.origin !== globalThis.location.origin || !url.pathname.startsWith(vendorRoot.pathname)) {
    return Promise.reject(new Error('READER_ARTIFACT_URL_INVALID'));
  }
  return fetch(url, {
    ...init,
    method: 'GET',
    credentials: 'same-origin',
    cache: 'no-store',
    redirect: 'error'
  });
}
