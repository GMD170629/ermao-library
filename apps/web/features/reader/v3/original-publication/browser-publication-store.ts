import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_RULE_IDS,
  readerSafetyAcceptsMimeType,
  readerSafetyFormatPolicy,
  type ReaderOriginalResource
} from '@shuku/reader-core';
import { withBasePath } from '../../../../lib/base-path';
import { privateCacheName, privateCacheNamespace } from '../../../../lib/pwa/private-cache-namespace';
import { ReaderSafetyPolicyError, rejectReaderSafety } from '../security/reader-safety-policy';

const STORE_VERSION = 'reader-original-v1';
const CACHE_KEY_ROOT = '/__shuku_reader_originals__/';

export type OriginalDownloadProgress = Readonly<{
  loadedBytes: number;
  totalBytes: number;
  percent: number;
}>;

export type OriginalPublicationDescriptor = ReaderOriginalResource & Readonly<{
  namespace: string;
}>;

export class OriginalPublicationStoreError extends Error {
  constructor(readonly code: string, options?: ErrorOptions) {
    super(code, options);
    this.name = 'OriginalPublicationStoreError';
  }
}

export type OriginalDownloadTransport = (
  descriptor: OriginalPublicationDescriptor,
  signal: AbortSignal
) => Promise<Response>;

type CacheEntryPort = Pick<Cache, 'match' | 'put' | 'delete' | 'keys'>;
type CacheStoragePort = { open(name: string): Promise<CacheEntryPort> };

function normalizedMime(value: string): string {
  return value.split(';', 1)[0]?.trim().toLowerCase() ?? '';
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
  const formatPolicy = readerSafetyFormatPolicy(descriptor.sourceFormat);
  if (!formatPolicy
    || formatPolicy.morphology !== 'REFLOWABLE'
    || !readerSafetyAcceptsMimeType(formatPolicy, descriptor.mimeType)) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_EXACT_FORMAT_MIME);
  }
  const url = new URL(descriptor.downloadUrl, origin);
  const apiPath = new URL(withBasePath('/api/'), origin).pathname;
  if (url.origin !== origin || !url.pathname.startsWith(apiPath)) {
    throw new OriginalPublicationStoreError('ORIGINAL_DOWNLOAD_URL_INVALID');
  }
}

function cacheRequest(descriptor: OriginalPublicationDescriptor, origin: string): Request {
  const parts = [descriptor.resourceId, descriptor.assetId, descriptor.assetVersion, descriptor.sourceFormat]
    .map(encodeURIComponent)
    .join('/');
  return new Request(new URL(`${CACHE_KEY_ROOT}${parts}`, origin), {
    method: 'GET',
    credentials: 'same-origin'
  });
}

async function deleteSupersededEntries(
  cache: CacheEntryPort,
  activeRequest: Request,
  descriptor: OriginalPublicationDescriptor,
  origin: string
): Promise<void> {
  const identityPrefix = `${CACHE_KEY_ROOT}${encodeURIComponent(descriptor.resourceId)}/${encodeURIComponent(descriptor.assetId)}/`;
  for (const request of await cache.keys()) {
    const url = new URL(request.url, origin);
    if (url.origin === origin && url.pathname.startsWith(identityPrefix) && request.url !== activeRequest.url) {
      await cache.delete(request);
    }
  }
}

function metadataHeaders(descriptor: OriginalPublicationDescriptor): Headers {
  const headers = new Headers({
    'Content-Type': descriptor.mimeType,
    'Content-Length': String(descriptor.sizeBytes),
    'X-Shuku-Resource-Id': descriptor.resourceId,
    'X-Shuku-Asset-Id': descriptor.assetId,
    'X-Shuku-Asset-Version': descriptor.assetVersion,
    'X-Shuku-Source-Format': descriptor.sourceFormat,
    'X-Shuku-Original-Complete': '1'
  });
  return headers;
}

function matchesMetadata(response: Response, descriptor: OriginalPublicationDescriptor): boolean {
  return response.headers.get('X-Shuku-Original-Complete') === '1'
    && response.headers.get('X-Shuku-Resource-Id') === descriptor.resourceId
    && response.headers.get('X-Shuku-Asset-Id') === descriptor.assetId
    && response.headers.get('X-Shuku-Asset-Version') === descriptor.assetVersion
    && response.headers.get('X-Shuku-Source-Format') === descriptor.sourceFormat
    && response.headers.get('Content-Length') === String(descriptor.sizeBytes)
    && normalizedMime(response.headers.get('Content-Type') ?? '') === normalizedMime(descriptor.mimeType);
}

async function validatedBlob(
  cache: CacheEntryPort,
  request: Request,
  descriptor: OriginalPublicationDescriptor
): Promise<Blob | null> {
  const cached = await cache.match(request);
  if (!cached || !matchesMetadata(cached, descriptor)) {
    if (cached) await cache.delete(request);
    return null;
  }
  const blob = await cached.blob();
  if (blob.size !== descriptor.sizeBytes || normalizedMime(blob.type) !== normalizedMime(descriptor.mimeType)) {
    await cache.delete(request);
    return null;
  }
  return blob;
}

export class BrowserPublicationStore {
  constructor(
    private readonly cacheStorage: CacheStoragePort = window.caches,
    private readonly transport: OriginalDownloadTransport,
    private readonly origin = window.location.origin
  ) {}

  async ensure(
    descriptor: OriginalPublicationDescriptor,
    options: Readonly<{
      signal: AbortSignal;
      onProgress?: (progress: OriginalDownloadProgress) => void;
    }>
  ): Promise<Readonly<{ blob: Blob; cacheHit: boolean }>> {
    assertDescriptor(descriptor, this.origin);
    const cache = await this.cacheStorage.open(privateCacheName(descriptor.namespace, STORE_VERSION));
    const request = cacheRequest(descriptor, this.origin);
    await deleteSupersededEntries(cache, request, descriptor, this.origin);
    const cached = await validatedBlob(cache, request, descriptor);
    if (cached) {
      options.onProgress?.({ loadedBytes: descriptor.sizeBytes, totalBytes: descriptor.sizeBytes, percent: 100 });
      return { blob: cached, cacheHit: true };
    }
    await cache.delete(request);
    options.onProgress?.({ loadedBytes: 0, totalBytes: descriptor.sizeBytes, percent: 0 });
    try {
      const response = await this.transport(descriptor, options.signal);
      if (!response.ok || response.status !== 200 || !response.body) {
        throw new OriginalPublicationStoreError('ORIGINAL_RESPONSE_INVALID');
      }
      if (response.headers.get('Content-Length') !== String(descriptor.sizeBytes)) {
        throw new OriginalPublicationStoreError('ORIGINAL_LENGTH_INVALID');
      }
      if (response.headers.get('X-Asset-Version') !== descriptor.assetVersion) {
        throw new OriginalPublicationStoreError('ORIGINAL_VERSION_CHANGED');
      }
      if (normalizedMime(response.headers.get('Content-Type') ?? '') !== normalizedMime(descriptor.mimeType)) {
        rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_EXACT_FORMAT_MIME);
      }
      let loadedBytes = 0;
      const meter = new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) {
          loadedBytes += chunk.byteLength;
          if (loadedBytes > descriptor.sizeBytes) {
            controller.error(new OriginalPublicationStoreError('ORIGINAL_LENGTH_INVALID'));
            return;
          }
          options.onProgress?.({
            loadedBytes,
            totalBytes: descriptor.sizeBytes,
            percent: Math.min(100, (loadedBytes / descriptor.sizeBytes) * 100)
          });
          controller.enqueue(chunk);
        },
        flush() {
          if (loadedBytes !== descriptor.sizeBytes) {
            throw new OriginalPublicationStoreError('ORIGINAL_LENGTH_INVALID');
          }
        }
      });
      await cache.put(request, new Response(response.body.pipeThrough(meter, { signal: options.signal }), {
        status: 200,
        headers: metadataHeaders(descriptor)
      }));
      const stored = await validatedBlob(cache, request, descriptor);
      if (!stored) throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO');
      return { blob: stored, cacheHit: false };
    } catch (cause) {
      await cache.delete(request).catch(() => false);
      if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
      if (cause instanceof OriginalPublicationStoreError) throw cause;
      if (cause instanceof ReaderSafetyPolicyError) throw cause;
      throw new OriginalPublicationStoreError('ORIGINAL_CACHE_IO', { cause });
    }
  }
}

export function browserPublicationNamespace(userId: string, authorizationVersion: number): string {
  const namespace = privateCacheNamespace(userId, authorizationVersion);
  if (!namespace) {
    throw new OriginalPublicationStoreError('ORIGINAL_NAMESPACE_INVALID');
  }
  return namespace;
}
