import type { ReaderSafetyRuleId } from '@shuku/reader-core';

export type MobiResourceDescriptor = Readonly<{
  index: number;
  category: number;
  sourceName: string;
  mediaType: string;
  decodedLength: number;
}>;

export type MobiTocEntry = Readonly<{
  title: string;
  resourceIndex: number;
  fragment: string | null;
  parentIndex: number | null;
}>;

export type MobiOpenResult = Readonly<{
  title: string | null;
  language: string | null;
  resources: readonly MobiResourceDescriptor[];
  readingOrder: readonly number[];
  toc: readonly MobiTocEntry[];
}>;

export type MobiWorkerRequest =
  | Readonly<{ requestId: number; type: 'open'; blob: Blob; filename: string }>
  | Readonly<{ requestId: number; type: 'read'; resourceIndex: number }>
  | Readonly<{ requestId: number; type: 'close' }>;

export type MobiWorkerResponse =
  | Readonly<{ requestId: number; ok: true; type: 'open'; result: MobiOpenResult }>
  | Readonly<{ requestId: number; ok: true; type: 'read'; bytes: ArrayBuffer }>
  | Readonly<{ requestId: number; ok: true; type: 'close' }>
  | Readonly<{ requestId: number; ok: false; code: string; ruleId?: ReaderSafetyRuleId }>;
