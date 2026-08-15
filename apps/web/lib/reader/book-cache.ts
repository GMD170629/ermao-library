import type { ReflowableFormat } from '@shuku/reader-core';

export type ReaderBookCacheIdentity = {
  userId: string;
  volumeId: string;
};

export type CachedReaderBookFile = ReaderBookCacheIdentity & {
  key: string;
  userVolumeKey: string;
  format: ReflowableFormat;
  mimeType: string;
  sizeBytes: number;
  blob: Blob;
  createdAt: number;
};

export interface ReaderBookCache {
  getBookFile(identity: ReaderBookCacheIdentity): Promise<CachedReaderBookFile | null>;
  putBookFile(file: CachedReaderBookFile): Promise<void>;
  deleteBookFile(identity: ReaderBookCacheIdentity): Promise<void>;
}

export function readerBookCacheKey(identity: ReaderBookCacheIdentity) {
  return [identity.userId, identity.volumeId]
    .map(encodeURIComponent)
    .join('::');
}

export function readerBookUserVolumeKey(identity: Pick<ReaderBookCacheIdentity, 'userId' | 'volumeId'>) {
  return [identity.userId, identity.volumeId].map(encodeURIComponent).join('::');
}
