/// <reference lib="webworker" />

import { READER_SAFETY_BUDGETS, READER_SAFETY_RULE_IDS } from '@shuku/reader-core';
import type {
  TextPublicationChapter,
  TextPublicationFormat,
  TextPublicationResult,
  TextPublicationTocEntry,
  TextWorkerRequest,
  TextWorkerResponse
} from './text-worker-protocol';
import {
  chapterEntriesToToc,
  chapterResultTextBytes,
  parseXmlWithChapterCore,
  parseTxtWithChapterCore,
  type ChapterXmlEvent
} from './chapter-core';
import { parseStrictFb2 } from './strict-fb2-parser';
import { decodePublicationText } from './text-decoder';
import {
  ReaderSafetyImplementationError,
  ReaderSafetyPolicyError,
  rejectReaderSafety
} from '../security/reader-safety-policy';

const MAX_TEXT_BYTES = READER_SAFETY_BUDGETS.originalMaxBytes;
const MAX_TEXT_MEMORY_BYTES = READER_SAFETY_BUDGETS.txtMemoryMaxBytes;

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
  return decodePublicationText(bytes);
}

function xhtml(title: string, body: string): ArrayBuffer {
  return new TextEncoder().encode(
    `<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>${escapeHtml(title)}</title></head><body>${body}</body></html>`
  ).buffer;
}

function bareHref(href: string): string {
  return href.split('#', 1)[0] ?? href;
}

function sliceUtf8(bytes: Uint8Array, start: number, end: number): string {
  const safeStart = Math.max(0, Math.min(bytes.byteLength, start));
  const safeEnd = Math.max(safeStart, Math.min(bytes.byteLength, end));
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(safeStart, safeEnd));
  } catch {
    throw new Error('CHAPTER_RESULT_UTF8_INVALID');
  }
}

function validTextResourceHref(href: string): boolean {
  return Boolean(href)
    && !href.startsWith('/')
    && !href.startsWith('../')
    && !/^[a-z][a-z\d+.-]*:/iu.test(href);
}

export function materializeTextChapter(
  href: string,
  chapterTitle: string,
  body: string,
  headingId?: string
): TextPublicationChapter {
  const paragraphs = body.split(/\n{2,}/).map((paragraph) => (
    `<p>${escapeHtml(paragraph).replaceAll('\n', '<br/>')}</p>`
  )).join('');
  const heading = headingId === undefined
    ? ''
    : `<h1 id="${escapeHtml(headingId)}">${escapeHtml(chapterTitle)}</h1>`;
  return {
    href,
    type: 'application/xhtml+xml',
    title: chapterTitle,
    bytes: xhtml(chapterTitle, `${heading}${paragraphs}`),
    positionLength: body.length
  };
}

export function materializeFb2Chapter(
  section: Readonly<{
    resourceHref?: string;
    href?: string;
    title: string | null;
    paragraphs: readonly string[];
    text: string;
    events: readonly ChapterXmlEvent[];
    sourceStart?: number;
  }>,
  chapterTitle: string,
): TextPublicationChapter {
  const resourceHref = section.resourceHref ?? section.href ?? '';
  const body: string[] = [];
  const stack: Array<Readonly<{
    name: string;
    renderedSection: boolean;
    renderedParagraph: boolean;
    title: boolean;
  }>> = [];
  let sectionDepth = 0;
  let titleCapture: { depth: number; parts: string[] } | null = null;
  const titleText = (parts: readonly string[]): string => parts.join('');
  for (const event of section.events) {
    if (event.kind === 'start') {
      const name = event.name ?? '';
      const inTitle = titleCapture !== null;
      if (name === 'section') {
        sectionDepth += 1;
        const separator = event.targetHref?.indexOf('#') ?? -1;
        const anchor = separator >= 0 ? event.targetHref?.slice(separator + 1) : null;
        if (!inTitle && anchor) body.push(`<section id="${escapeHtml(anchor)}">`);
        stack.push({
          name,
          renderedSection: !inTitle && Boolean(anchor),
          renderedParagraph: false,
          title: false
        });
        continue;
      }
      if (name === 'title') {
        titleCapture = { depth: Math.min(6, Math.max(1, sectionDepth || 1)), parts: [] };
        stack.push({
          name,
          renderedSection: false,
          renderedParagraph: false,
          title: true
        });
        continue;
      }
      const renderedParagraph = name === 'p' && !inTitle;
      if (renderedParagraph) body.push('<p>');
      stack.push({
        name,
        renderedSection: false,
        renderedParagraph,
        title: false
      });
      continue;
    }
    if (event.kind === 'text') {
      if (titleCapture) {
        titleCapture.parts.push(event.text ?? '');
      } else if (event.text) {
        body.push(escapeHtml(event.text));
      }
      continue;
    }
    const frame = stack.pop();
    if (!frame) continue;
    if (frame.title) {
      const capture = titleCapture;
      titleCapture = null;
      const value = capture ? titleText(capture.parts) : '';
      if (value.trim()) body.push(`<h${capture?.depth ?? 1}>${escapeHtml(value)}</h${capture?.depth ?? 1}>`);
    } else if (frame.renderedParagraph) {
      body.push('</p>');
    } else if (frame.name === 'section') {
      if (frame.renderedSection) body.push('</section>');
      sectionDepth = Math.max(0, sectionDepth - 1);
    }
  }
  const rendered = body.join('');
  return {
    href: resourceHref,
    type: 'application/xhtml+xml',
    title: chapterTitle,
    bytes: xhtml(chapterTitle, rendered || `<p>${escapeHtml(section.text)}</p>`),
    positionLength: section.text.length
  };
}

async function parseTxt(value: string, title: string): Promise<TextPublicationResult> {
  const parsed = await parseTxtWithChapterCore(value);
  const normalizedBytes = chapterResultTextBytes(parsed);
  if (normalizedBytes.byteLength === 0) throw new Error('PUBLICATION_TXT_EMPTY');
  // The core result is already validated and in preorder. Keep its authored
  // entries intact; this layer only materializes the source ranges it names.
  const entries = parsed.entries;
  const toc: readonly TextPublicationTocEntry[] = chapterEntriesToToc(entries);
  const chapters: TextPublicationChapter[] = [];
  const firstChapter = entries.find((entry) => entry.href !== null);
  const firstStart = firstChapter?.sourceStart ?? 0;
  if (entries.length > 0 && firstStart > 0) chapters.push(materializeTextChapter(
    'text/frontmatter.xhtml',
    title,
    sliceUtf8(normalizedBytes, 0, firstStart)
  ));
  for (const entry of entries) {
    if (!entry.href) continue;
    const resourceHref = bareHref(entry.href);
    if (!validTextResourceHref(resourceHref)) throw new Error('CHAPTER_TARGET_INVALID');
    const headingId = entry.href.split('#')[1];
    chapters.push(materializeTextChapter(
      resourceHref,
      entry.title,
      sliceUtf8(normalizedBytes, entry.contentStart, entry.sourceEnd),
      headingId
    ));
  }
  if (chapters.length === 0) {
    chapters.push(materializeTextChapter(
      'text/body.xhtml',
      title,
      sliceUtf8(normalizedBytes, 0, normalizedBytes.byteLength)
    ));
  }
  return { title, language: null, chapters, toc };
}

async function parseFb2(value: string, fallbackTitle: string): Promise<TextPublicationResult> {
  const parsed = parseStrictFb2(value);
  const title = parsed.title || fallbackTitle;
  const chapterTree = await parseXmlWithChapterCore('fb2', parsed.events);
  const toc = chapterEntriesToToc(chapterTree.entries) as readonly TextPublicationTocEntry[];
  const orderedSources = [...parsed.bodyFragments, ...parsed.sections]
    .sort((left, right) => (
      (left.sourceStart ?? Number.MAX_SAFE_INTEGER) - (right.sourceStart ?? Number.MAX_SAFE_INTEGER)
    ));
  const chapters = orderedSources.map((section, index): TextPublicationChapter => {
    const chapterTitle = section.title || `${title} ${index + 1}`;
    return materializeFb2Chapter(section, chapterTitle);
  });
  return { title, language: parsed.language, chapters, toc };
}

async function openText(blob: Blob, format: TextPublicationFormat, fallbackTitle: string): Promise<TextPublicationResult> {
  const value = await decodeText(blob, format);
  return format === 'txt' ? parseTxt(value, fallbackTitle) : parseFb2(value, fallbackTitle);
}

function respond(value: TextWorkerResponse, transfer: Transferable[] = []): void {
  self.postMessage(value, transfer);
}

if (typeof self !== 'undefined') {
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
}
