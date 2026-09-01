import { createLocalPublication, type ReadiumPublication } from './local-publication';
import { parseTextPublication } from './text-worker-client';
import type { TextPublicationFormat } from './text-worker-protocol';
import type { ReaderReadingProgression, ReaderWritingMode } from '@shuku/reader-core';

export async function openTextPublication(
  blob: Blob,
  format: TextPublicationFormat,
  fallbackTitle: string,
  readingProgression: ReaderReadingProgression,
  writingMode: ReaderWritingMode,
  signal?: AbortSignal
): Promise<ReadiumPublication> {
  const parsed = await parseTextPublication(blob, format, fallbackTitle, signal);
  return createLocalPublication({
    title: parsed.title,
    language: parsed.language,
    readingProgression,
    writingMode,
    readingOrder: parsed.chapters.map((chapter) => ({
      href: chapter.href,
      type: chapter.type,
      title: chapter.title,
      size: chapter.bytes.byteLength,
      positionLength: chapter.positionLength,
      read: async () => new Uint8Array(chapter.bytes)
    }))
  });
}
