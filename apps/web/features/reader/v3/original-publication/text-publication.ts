import { createLocalPublication, type ReadiumPublication } from './local-publication';
import { parseTextPublication } from './text-worker-client';
import type { TextPublicationFormat } from './text-worker-protocol';

export async function openTextPublication(
  blob: Blob,
  format: TextPublicationFormat,
  fallbackTitle: string,
  signal?: AbortSignal
): Promise<ReadiumPublication> {
  const parsed = await parseTextPublication(blob, format, fallbackTitle, signal);
  return createLocalPublication({
    title: parsed.title,
    language: parsed.language,
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
