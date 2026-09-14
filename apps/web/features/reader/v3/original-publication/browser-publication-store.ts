import { READER_SAFETY_BUDGETS, READER_SAFETY_RULE_IDS } from '@shuku/reader-core';
import { withBasePath } from '../../../../lib/base-path';
import { privateCacheNamespace } from '../../../../lib/pwa/private-cache-namespace';
import { ReaderSafetyPolicyError, rejectReaderSafety } from '../security/reader-safety-policy';
import { ORIGINAL_CHUNK_BYTES, OriginalPublicationStoreError, type OriginalDownloadProgress, type OriginalDownloadTransport,
  type OriginalPublicationDescriptor, type OriginalStoragePort, type OriginalStoreSession } from './original-store-contract';
export { OriginalPublicationStoreError, type OriginalDownloadProgress, type OriginalDownloadTransport,
  type OriginalPublicationDescriptor } from './original-store-contract';

function isQuotaExceededError(cause: unknown): boolean {
  return cause instanceof Error && cause.name === 'QuotaExceededError';
}
function throwPublicationStoreError(cause: unknown): never {
  if (cause instanceof OriginalPublicationStoreError || cause instanceof ReaderSafetyPolicyError) throw cause;
  if (cause instanceof Error && cause.name === 'AbortError') throw cause;
  throw new OriginalPublicationStoreError(isQuotaExceededError(cause) ? 'ORIGINAL_CACHE_QUOTA' : 'ORIGINAL_CACHE_IO', { cause });
}
function networkError(cause: unknown, signal: AbortSignal): never {
  signal.throwIfAborted();
  if (cause instanceof Error && cause.name === 'AbortError') throw cause;
  if (cause instanceof Error && /^[A-Z][A-Z0-9_]+$/.test(cause.message)) {
    throw new OriginalPublicationStoreError(cause.message, { cause });
  }
  throw new OriginalPublicationStoreError('NETWORK_UNAVAILABLE', { cause });
}

function assertDescriptor(descriptor: OriginalPublicationDescriptor, origin: string): void {
  if (!descriptor.namespace.trim() || !descriptor.resourceId.trim() || !descriptor.assetId.trim()) {
    throw new OriginalPublicationStoreError('ORIGINAL_DESCRIPTOR_INVALID');
  }
  if (descriptor.assetVersion !== `${descriptor.sizeBytes}:${descriptor.mtimeMs}`) {
    throw new OriginalPublicationStoreError('ORIGINAL_VERSION_INVALID');
  }
  if (!Number.isSafeInteger(descriptor.sizeBytes) || descriptor.sizeBytes < 0) {
    throw new OriginalPublicationStoreError('ORIGINAL_DESCRIPTOR_INVALID');
  }
  if (descriptor.sizeBytes > READER_SAFETY_BUDGETS.originalMaxBytes) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_ORIGINAL_MAX_BYTES);
  }
  if (!Number.isSafeInteger(descriptor.mtimeMs) || descriptor.mtimeMs < 0) {
    throw new OriginalPublicationStoreError('ORIGINAL_VERSION_INVALID');
  }
  const url = new URL(descriptor.downloadUrl, origin);
  const apiPath = new URL(withBasePath('/api/'), origin).pathname;
  if (url.origin !== origin || !url.pathname.startsWith(apiPath)) {
    throw new OriginalPublicationStoreError('ORIGINAL_DOWNLOAD_URL_INVALID');
  }
}


type DownloadOptions = Readonly<{ signal: AbortSignal; onProgress?: (progress: OriginalDownloadProgress) => void }>;

export class BrowserPublicationStore {
  constructor(
    private readonly storage: OriginalStoragePort,
    private readonly transport: OriginalDownloadTransport,
    private readonly origin = window.location.origin
  ) {}

  private async download(session: OriginalStoreSession, descriptor: OriginalPublicationDescriptor, options: DownloadOptions): Promise<Blob> {
    const { signal } = options;
    signal.throwIfAborted();
    options.onProgress?.({ loadedBytes: 0, totalBytes: descriptor.sizeBytes, percent: 0 });
    const response = await this.transport(descriptor, signal).catch((cause: unknown) => networkError(cause, signal));
    let succeeded = false;
    let published = false;
    const reader = response.body?.getReader();
    if (!reader) throw new OriginalPublicationStoreError('ORIGINAL_RESPONSE_INVALID');
    const cancel = () => { void reader.cancel(signal.reason).catch(() => undefined); };
    signal.addEventListener('abort', cancel, { once: true });
    let artifact: Awaited<ReturnType<OriginalStoragePort['begin']>> | null = null;
    try {
      signal.throwIfAborted();
      if (!response.ok || response.status !== 200) throw new OriginalPublicationStoreError('ORIGINAL_RESPONSE_INVALID');
      if (response.headers.get('Content-Length') !== String(descriptor.sizeBytes)) throw new OriginalPublicationStoreError('ORIGINAL_LENGTH_INVALID');
      if (response.headers.get('X-Asset-Version') !== descriptor.assetVersion) throw new OriginalPublicationStoreError('ORIGINAL_VERSION_CHANGED');
      artifact = await this.storage.begin(session, descriptor);
      let loadedBytes = 0;
      for (;;) {
        signal.throwIfAborted();
        const result = await reader.read().catch((cause: unknown) => networkError(cause, signal));
        signal.throwIfAborted();
        if (result.done) break;
        if (loadedBytes + result.value.byteLength > descriptor.sizeBytes) throw new OriginalPublicationStoreError('ORIGINAL_LENGTH_INVALID');
        for (let offset = 0; offset < result.value.byteLength; offset += ORIGINAL_CHUNK_BYTES) {
          signal.throwIfAborted();
          const bytes = result.value.slice(offset, offset + ORIGINAL_CHUNK_BYTES);
          await this.storage.append(artifact, new Blob([bytes]));
          loadedBytes += bytes.byteLength;
          options.onProgress?.({ loadedBytes, totalBytes: descriptor.sizeBytes,
            percent: descriptor.sizeBytes === 0 ? 100 : Math.min(100, loadedBytes / descriptor.sizeBytes * 100) });
        }
      }
      if (loadedBytes !== descriptor.sizeBytes) throw new OriginalPublicationStoreError('ORIGINAL_LENGTH_INVALID');
      signal.throwIfAborted();
      await this.storage.complete(artifact, signal);
      published = true;
      signal.throwIfAborted();
      const blob = await this.storage.read(session, descriptor);
      signal.throwIfAborted();
      if (!blob) throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO');
      succeeded = true;
      return blob;
    } finally {
      signal.removeEventListener('abort', cancel);
      try {
        if (!succeeded) {
          // Cancel failed transfers before retrying; release only this attempt's bytes.
          await reader.cancel().catch(() => undefined);
          if (artifact && !published) await this.storage.discard(artifact);
        }
      } finally { reader.releaseLock(); }
    }
  }

  async ensure(descriptor: OriginalPublicationDescriptor, options: DownloadOptions): Promise<Readonly<{ blob: Blob; cacheHit: boolean }>> {
    assertDescriptor(descriptor, this.origin);
    try {
      options.signal.throwIfAborted();
      const session = await this.storage.session(descriptor.namespace);
      const cached = await this.storage.read(session, descriptor);
      options.signal.throwIfAborted();
      if (cached) {
        options.onProgress?.({ loadedBytes: descriptor.sizeBytes, totalBytes: descriptor.sizeBytes, percent: 100 });
        return { blob: cached, cacheHit: true };
      }
      try {
        return { blob: await this.download(session, descriptor, options), cacheHit: false };
      } catch (cause) {
        options.signal.throwIfAborted();
        if (!isQuotaExceededError(cause) || await this.storage.reclaim(session, descriptor) === 0) throw cause;
        return { blob: await this.download(session, descriptor, options), cacheHit: false };
      }
    } catch (cause) { throwPublicationStoreError(cause); }
  }
}

export function browserPublicationNamespace(userId: string, authorizationVersion: number): string {
  const namespace = privateCacheNamespace(userId, authorizationVersion);
  if (!namespace) throw new OriginalPublicationStoreError('ORIGINAL_NAMESPACE_INVALID');
  return namespace;
}
