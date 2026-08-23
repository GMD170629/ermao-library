import type { ReflowableFormat } from '@shuku/reader-core';

export type ReaderResourceCacheIdentity = {
  userId: string;
  resourceId: string;
};

export type CachedReaderResource = ReaderResourceCacheIdentity & {
  key: string;
  userResourceKey: string;
  format: ReflowableFormat;
  mimeType: string;
  sizeBytes: number;
  blob: Blob;
  createdAt: number;
};

export interface ReaderResourceCache {
  getResource(identity: ReaderResourceCacheIdentity): Promise<CachedReaderResource | null>;
  putResource(resource: CachedReaderResource): Promise<void>;
  deleteResource(identity: ReaderResourceCacheIdentity): Promise<void>;
}

export function readerResourceCacheKey(identity: ReaderResourceCacheIdentity) {
  return [identity.userId, identity.resourceId]
    .map(encodeURIComponent)
    .join('::');
}

export function readerResourceUserKey(identity: Pick<ReaderResourceCacheIdentity, 'userId' | 'resourceId'>) {
  return [identity.userId, identity.resourceId].map(encodeURIComponent).join('::');
}
