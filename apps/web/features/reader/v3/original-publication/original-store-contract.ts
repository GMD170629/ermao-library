import type { ReaderOriginalResource } from '@shuku/reader-core';

export const ORIGINAL_CHUNK_BYTES = 1024 * 1024;

export type OriginalDownloadProgress = Readonly<{
  loadedBytes: number;
  totalBytes: number;
  percent: number;
}>;
export type OriginalPublicationDescriptor = ReaderOriginalResource & Readonly<{ namespace: string }>;
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
export type OriginalStoreSession = Readonly<{ namespace: string; epoch: string }>;
export type OriginalArtifact = Readonly<{ id: string; session: OriginalStoreSession }>;
export interface OriginalStoragePort {
  session(namespace: string): Promise<OriginalStoreSession>;
  read(session: OriginalStoreSession, descriptor: OriginalPublicationDescriptor): Promise<Blob | null>;
  begin(session: OriginalStoreSession, descriptor: OriginalPublicationDescriptor): Promise<OriginalArtifact>;
  append(artifact: OriginalArtifact, chunk: Blob): Promise<void>;
  complete(artifact: OriginalArtifact, signal: AbortSignal): Promise<void>;
  discard(artifact: OriginalArtifact): Promise<void>;
  reclaim(session: OriginalStoreSession, descriptor: OriginalPublicationDescriptor): Promise<number>;
}
