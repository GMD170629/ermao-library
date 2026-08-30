/// <reference lib="webworker" />

import { READER_SAFETY_BUDGETS, READER_SAFETY_RULE_IDS } from '@shuku/reader-core';
import type {
  TextPublicationChapter,
  TextPublicationFormat,
  TextPublicationResult,
  TextWorkerRequest,
  TextWorkerResponse
} from './text-worker-protocol';
import { parseStrictFb2 } from './strict-fb2-parser';
import {
  ReaderSafetyImplementationError,
  ReaderSafetyPolicyError,
  rejectReaderSafety
} from '../security/reader-safety-policy';

const MAX_TEXT_BYTES = READER_SAFETY_BUDGETS.originalMaxBytes;
const MAX_TEXT_MEMORY_BYTES = READER_SAFETY_BUDGETS.txtMemoryMaxBytes;
const TXT_CHUNK_CHARS = READER_SAFETY_BUDGETS.txtChunkMaxCharacters;

function property(value: unknown, key: PropertyKey): unknown {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return undefined;
  return Reflect.get(value, key);
}

function request(value: unknown): TextWorkerRequest | null {
  const requestId = property(value, 'requestId');
  const type = property(value, 'type');
  const blob = property(value, 'blob');
  const format = property(value, 'format');
  const fallbackTitle = property(value, 'fallbackTitle');
  if (
    !Number.isSafeInteger(requestId)
    || Number(requestId) < 0
    || type !== 'open'
    || !(blob instanceof Blob)
    || (format !== 'txt' && format !== 'fb2')
    || typeof fallbackTitle !== 'string'
  ) return null;
  return { requestId: Number(requestId), type, blob, format, fallbackTitle };
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

async function decodeText(blob: Blob, format: TextPublicationFormat): Promise<string> {
  if (blob.size > MAX_TEXT_BYTES) rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_ORIGINAL_MAX_BYTES);
  if (format === 'txt' && blob.size > MAX_TEXT_MEMORY_BYTES) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.TXT_MEMORY_BUDGET);
  }
  if (format === 'fb2' && blob.size > READER_SAFETY_BUDGETS.fb2TextMaxBytes) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.FB2_STRUCTURE_BUDGET);
  }
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const candidates: readonly Readonly<{ encoding: string; offset: number }>[] = bytes[0] === 0xff && bytes[1] === 0xfe
    ? [{ encoding: 'utf-16le', offset: 2 }]
    : bytes[0] === 0xfe && bytes[1] === 0xff
      ? [{ encoding: 'utf-16be', offset: 2 }]
      : [{ encoding: 'utf-8', offset: 0 }, { encoding: 'gb18030', offset: 0 }];
  for (const candidate of candidates) {
    try {
      return new TextDecoder(candidate.encoding, { fatal: true })
        .decode(bytes.subarray(candidate.offset))
        .replace(/^\uFEFF/, '');
    } catch {
      // Try the next explicitly supported encoding.
    }
  }
  throw new Error('PUBLICATION_TXT_ENCODING_UNSUPPORTED');
}

function xhtml(title: string, body: string): ArrayBuffer {
  return new TextEncoder().encode(
    `<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>${escapeHtml(title)}</title></head><body>${body}</body></html>`
  ).buffer;
}

function parseTxt(value: string, title: string): TextPublicationResult {
  const normalized = value.replace(/\r\n?/g, '\n').trim();
  if (!normalized) throw new Error('PUBLICATION_TXT_EMPTY');
  const chunks: string[] = [];
  for (let offset = 0; offset < normalized.length; offset += TXT_CHUNK_CHARS) {
    chunks.push(normalized.slice(offset, offset + TXT_CHUNK_CHARS));
  }
  const chapters = chunks.map((chunk, index): TextPublicationChapter => {
    const chapterTitle = chunks.length === 1 ? title : `${title} ${index + 1}`;
    const paragraphs = chunk.split(/\n{2,}/).map((paragraph) => (
      `<p>${escapeHtml(paragraph).replaceAll('\n', '<br/>')}</p>`
    )).join('');
    return {
      href: `text/${index}.xhtml`,
      type: 'application/xhtml+xml',
      title: chapterTitle,
      bytes: xhtml(chapterTitle, paragraphs),
      positionLength: chunk.length
    };
  });
  return { title, language: null, chapters };
}

function parseFb2(value: string, fallbackTitle: string): TextPublicationResult {
  const parsed = parseStrictFb2(value);
  const title = parsed.title || fallbackTitle;
  const chapters = parsed.chapters.map((section, index): TextPublicationChapter => {
    const chapterTitle = section.title || `${title} ${index + 1}`;
    const paragraphs = section.paragraphs
      .map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`)
      .join('');
    return {
      href: `fb2/${index}.xhtml`,
      type: 'application/xhtml+xml',
      title: chapterTitle,
      bytes: xhtml(chapterTitle, `<h1>${escapeHtml(chapterTitle)}</h1>${paragraphs || `<p>${escapeHtml(section.text)}</p>`}`),
      positionLength: section.text.length
    };
  });
  return { title, language: parsed.language, chapters };
}

async function openText(blob: Blob, format: TextPublicationFormat, fallbackTitle: string): Promise<TextPublicationResult> {
  const value = await decodeText(blob, format);
  return format === 'txt' ? parseTxt(value, fallbackTitle) : parseFb2(value, fallbackTitle);
}

function respond(value: TextWorkerResponse, transfer: Transferable[] = []): void {
  self.postMessage(value, transfer);
}

self.addEventListener('message', (event: MessageEvent<unknown>) => {
  const incoming = request(event.data);
  if (!incoming) return;
  void openText(incoming.blob, incoming.format, incoming.fallbackTitle)
    .then((result) => respond(
      { requestId: incoming.requestId, ok: true, result },
      result.chapters.map((chapter) => chapter.bytes)
    ))
    .catch((reason) => respond({
      requestId: incoming.requestId,
      ok: false,
      code: reason instanceof Error && /^[A-Z][A-Z0-9_]+$/.test(reason.message)
        ? reason.message
        : 'PUBLICATION_PARSE_FAILED',
      ...(reason instanceof ReaderSafetyPolicyError || reason instanceof ReaderSafetyImplementationError
        ? { ruleId: reason.ruleId }
        : {})
    }));
});
