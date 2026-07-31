export type TxtBookSection = {
  id: string;
  size: number;
  load: () => string;
  unload: () => void;
  createDocument: () => Document;
};

export type TxtBookTocItem = {
  label: string;
  href: string;
};

export type TxtBook = {
  sections: TxtBookSection[];
  toc: TxtBookTocItem[];
  metadata: { title: string };
  dir: 'ltr';
  resolveHref: (href: string) => { index: number; anchor: (document: Document) => Element | null } | null;
  splitTOCHref: (href: string) => [string, null];
  getTOCFragment: (document: Document) => Element | null;
  destroy: () => void;
};

export class TxtEncodingError extends Error {
  readonly code = 'NOVEL_ENCODING_UNCERTAIN';

  constructor() {
    super('Unable to determine the TXT encoding reliably');
    this.name = 'TxtEncodingError';
  }
}

const utf8Bom = new Uint8Array([0xef, 0xbb, 0xbf]);
const utf16LeBom = new Uint8Array([0xff, 0xfe]);
const utf16BeBom = new Uint8Array([0xfe, 0xff]);
const chapterHeading = /^\s*(?:第[0-9０-９一二三四五六七八九十百千万零〇两]+[章节卷部篇回]|(?:chapter|part|volume)\s+[0-9ivxlcdm]+\b).{0,80}$/iu;
const targetSectionCharacters = 128 * 1024;

function startsWith(bytes: Uint8Array, prefix: Uint8Array) {
  return prefix.every((value, index) => bytes[index] === value);
}

function decodeStrict(bytes: Uint8Array, encoding: string) {
  return new TextDecoder(encoding, { fatal: true }).decode(bytes);
}

export function decodeTxt(bytes: ArrayBuffer | Uint8Array) {
  const value = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (!value.byteLength) throw new TxtEncodingError();
  try {
    if (startsWith(value, utf8Bom)) return decodeStrict(value.subarray(utf8Bom.length), 'utf-8');
    if (startsWith(value, utf16LeBom)) return decodeStrict(value.subarray(utf16LeBom.length), 'utf-16le');
    if (startsWith(value, utf16BeBom)) return decodeStrict(value.subarray(utf16BeBom.length), 'utf-16be');
    if (value.includes(0)) throw new TxtEncodingError();
    try {
      return decodeStrict(value, 'utf-8');
    } catch {
      return decodeStrict(value, 'gb18030');
    }
  } catch (reason) {
    if (reason instanceof TxtEncodingError) throw reason;
    throw new TxtEncodingError();
  }
}

type TxtChunk = { title: string; text: string };

function hardSplit(title: string, text: string) {
  const chunks: TxtChunk[] = [];
  let remaining = text.trim();
  let part = 1;
  while (remaining.length > targetSectionCharacters) {
    const candidate = remaining.slice(0, targetSectionCharacters);
    const paragraph = Math.max(candidate.lastIndexOf('\n\n'), candidate.lastIndexOf('\r\n\r\n'));
    const splitAt = paragraph >= targetSectionCharacters / 2 ? paragraph : targetSectionCharacters;
    chunks.push({ title: `${title} (${part})`, text: remaining.slice(0, splitAt).trim() });
    remaining = remaining.slice(splitAt).trim();
    part += 1;
  }
  if (remaining) chunks.push({ title: part === 1 ? title : `${title} (${part})`, text: remaining });
  return chunks;
}

export function splitTxtSections(text: string) {
  const normalized = text.replace(/\r\n?/g, '\n').replace(/^\uFEFF/, '').trim();
  if (!normalized) throw new TxtEncodingError();
  const lines = normalized.split('\n');
  const sections: TxtChunk[] = [];
  let title = '正文';
  let body: string[] = [];
  const flush = () => {
    const value = body.join('\n').trim();
    if (value) sections.push(...hardSplit(title, value));
    body = [];
  };
  for (const line of lines) {
    if (chapterHeading.test(line.trim())) {
      flush();
      title = line.trim();
    } else {
      body.push(line);
    }
  }
  flush();
  return sections.length ? sections : hardSplit('正文', normalized);
}

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function sectionMarkup(title: string, text: string) {
  const paragraphs = text.split(/\n{2,}/).map((paragraph) => paragraph.trim()).filter(Boolean);
  return `<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8"/><title>${escapeHtml(title)}</title></head>
<body><h1>${escapeHtml(title)}</h1>${paragraphs.map((paragraph) => `<p>${escapeHtml(paragraph).replaceAll('\n', '<br/>')}</p>`).join('')}</body></html>`;
}

function parseTxtHref(href: string) {
  const match = /^txt-section:(\d+)$/.exec(href);
  return match ? Number.parseInt(match[1] ?? '', 10) : Number.NaN;
}

export function makeTxtBook(text: string, title = 'TXT') : TxtBook {
  const chunks = splitTxtSections(text);
  const urls = new Map<number, string>();
  const documents = new Map<number, Document>();
  const encoder = new TextEncoder();
  const sections = chunks.map<TxtBookSection>((chunk, index) => {
    const markup = sectionMarkup(chunk.title, chunk.text);
    return {
      id: `txt-${index}`,
      size: encoder.encode(chunk.text).byteLength,
      load: () => {
        const current = urls.get(index);
        if (current) return current;
        const url = URL.createObjectURL(new Blob([markup], { type: 'application/xhtml+xml' }));
        urls.set(index, url);
        return url;
      },
      unload: () => {
        const url = urls.get(index);
        if (url) URL.revokeObjectURL(url);
        urls.delete(index);
      },
      createDocument: () => {
        const current = documents.get(index);
        if (current) return current;
        const document = new DOMParser().parseFromString(markup, 'application/xhtml+xml');
        documents.set(index, document);
        return document;
      }
    };
  });
  const toc = chunks.map((chunk, index) => ({ label: chunk.title, href: `txt-section:${index}` }));
  return {
    sections,
    toc,
    metadata: { title },
    dir: 'ltr',
    resolveHref: (href) => {
      const index = parseTxtHref(href);
      if (!Number.isInteger(index) || index < 0 || index >= sections.length) return null;
      return { index, anchor: (document) => document.body ?? document.documentElement };
    },
    splitTOCHref: (href) => [`txt-${parseTxtHref(href)}`, null],
    getTOCFragment: (document) => document.body ?? document.documentElement,
    destroy: () => sections.forEach((section) => section.unload())
  };
}
