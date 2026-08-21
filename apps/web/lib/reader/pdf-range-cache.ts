import type { PdfRangeCacheIdentity } from '@shuku/reader-core';

export type CachedPdfRangeChunk = Readonly<{
  bytes: Uint8Array;
  lastAccessedAt: number;
}>;

export interface PdfRangeCache {
  getPdfRangeChunk(identity: PdfRangeCacheIdentity, chunkIndex: number): Promise<CachedPdfRangeChunk | null>;
  putPdfRangeChunk(
    identity: PdfRangeCacheIdentity,
    chunkIndex: number,
    bytes: Uint8Array,
    protectedChunkKeys?: readonly string[]
  ): Promise<void>;
  deletePdfRangeNamespace(identity: Omit<PdfRangeCacheIdentity, 'resourceId'>): Promise<void>;
}
