import type { ReaderSafetyRuleId } from '@shuku/reader-core';

export type TextPublicationFormat = 'txt' | 'fb2';

export type TextPublicationChapter = Readonly<{
  href: string;
  type: 'application/xhtml+xml';
  title: string;
  bytes: ArrayBuffer;
  positionLength: number;
}>;

export type TextPublicationTocEntry = Readonly<{
  href: string | null;
  title: string;
  navigationKey?: string;
  children?: readonly TextPublicationTocEntry[];
}>;

export type TextPublicationResult = Readonly<{
  title: string;
  language: string | null;
  chapters: readonly TextPublicationChapter[];
  toc: readonly TextPublicationTocEntry[];
}>;

export type TextWorkerRequest = Readonly<{
  requestId: number;
  type: 'open';
  blob: Blob;
  format: TextPublicationFormat;
  fallbackTitle: string;
}>;

export type TextWorkerResponse =
  | Readonly<{ requestId: number; ok: true; result: TextPublicationResult }>
  | Readonly<{ requestId: number; ok: false; code: string; ruleId?: ReaderSafetyRuleId }>;
