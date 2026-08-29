import type { OriginalDownloadTransport } from '../browser-publication-store';
import { requestReaderResource } from '../../../api/client';

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
