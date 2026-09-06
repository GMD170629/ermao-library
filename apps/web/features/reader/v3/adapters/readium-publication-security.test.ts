import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import path from 'node:path';
import test from 'node:test';
import { pathToFileURL } from 'node:url';
import {
  BlobReader,
  BlobWriter,
  TextReader,
  Uint8ArrayReader,
  ZipReader,
  ZipWriter
} from '@zip.js/zip.js';
import {
  READER_SAFETY_IMPLEMENTATION_FAILURE_CODES,
  READER_SAFETY_RULE_IDS,
  ReaderSafetyImplementationError,
  ReaderSafetyPolicyError
} from '@shuku/reader-core';
import type { MobiOpenResult, MobiWorkerRequest } from '../original-publication/mobi-worker-protocol';
import { openMobiPublication } from '../original-publication/mobi-publication';
import { openReadiumPublication } from './readium-publication';
import {
  normalizeEpubArchivePath,
  preflightEpubArchiveEntries,
  readEpubArchiveEntry
} from '../security/epub-archive-safety';

const webRoot = path.resolve(import.meta.dirname, '../../../..');
const chapterArtifactRoot = path.resolve(webRoot, 'public/vendor/chapter-core');
const chapterRuntimeUrl = pathToFileURL(path.join(chapterArtifactRoot, 'ermao-chapters.mjs')).href;
register(`data:text/javascript,${encodeURIComponent(`
  const chapterRuntimeUrl = ${JSON.stringify(chapterRuntimeUrl)};
  export async function resolve(specifier, context, nextResolve) {
    if (specifier === '/vendor/chapter-core/ermao-chapters.mjs') {
      return { url: chapterRuntimeUrl, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  }
`)}`, { parentURL: import.meta.url });

class TestElement {
  readonly attributes: readonly never[] = [];
  readonly childNodes: readonly never[] = [];
  constructor(
    readonly localName: string,
    private readonly values: Readonly<Record<string, string>> = {},
    readonly textContent = ''
  ) {}

  get tagName(): string { return this.localName; }
  getAttribute(name: string): string | null { return this.values[name] ?? null; }
  getAttributeNS(_namespace: string, name: string): string | null { return this.getAttribute(name); }
  hasAttribute(name: string): boolean { return this.getAttribute(name) !== null; }
  querySelector(_selector: string): TestElement | null { return null; }
  remove(): void {}
  removeAttributeNS(_namespace: string | null, _localName: string): void {}
  setAttribute(_name: string, _value: string): void {}
  setAttributeNS(_namespace: string | null, _name: string, _value: string): void {}
  replaceWith(_replacement: TestElement): void {}
  append(..._nodes: readonly unknown[]): void {}
}

function attributesFrom(source: string): Record<string, string> {
  const values: Record<string, string> = {};
  for (const match of source.matchAll(/([A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*(['"])(.*?)\2/gu)) {
    const name = match[1];
    const value = match[3];
    if (name !== undefined && value !== undefined) values[name] = value;
  }
  return values;
}

class TestDocument {
  readonly documentElement = new TestElement('html');
  readonly body: TestElement;
  private readonly rootfile: TestElement | null;
  private readonly manifestItems: readonly TestElement[];
  private readonly spineElement: TestElement | null;
  private readonly spineItems: readonly TestElement[];
  private readonly title: TestElement | null;
  private readonly language: TestElement | null;
  readonly serialized: string;

  constructor(source: string) {
    this.serialized = source;
    const body = /<body\b[^>]*>([\s\S]*?)<\/body>/iu.exec(source)?.[1] ?? source.replace(/<[^>]+>/gu, '');
    this.body = new TestElement('body', {}, body.replace(/<[^>]+>/gu, '').trim());
    const rootfileMatch = /<rootfile\b([^>]*)>/iu.exec(source);
    this.rootfile = rootfileMatch
      ? new TestElement('rootfile', attributesFrom(rootfileMatch[1] ?? ''))
      : null;
    this.manifestItems = [...source.matchAll(/<item\b([^>]*)\/?>(?:\s*<\/item>)?/giu)]
      .map((match) => new TestElement('item', attributesFrom(match[1] ?? '')));
    const spineMatch = /<spine\b([^>]*)>/iu.exec(source);
    this.spineElement = spineMatch
      ? new TestElement('spine', attributesFrom(spineMatch[1] ?? ''))
      : null;
    this.spineItems = [...source.matchAll(/<itemref\b([^>]*)\/?>(?:\s*<\/itemref>)?/giu)]
      .map((match) => new TestElement('itemref', attributesFrom(match[1] ?? '')));
    const titleMatch = /<(?:dc:)?title\b[^>]*>([\s\S]*?)<\/(?:dc:)?title>/iu.exec(source);
    this.title = titleMatch ? new TestElement('title', {}, titleMatch[1]?.trim() ?? '') : null;
    const languageMatch = /<(?:dc:)?language\b[^>]*>([\s\S]*?)<\/(?:dc:)?language>/iu.exec(source);
    this.language = languageMatch ? new TestElement('language', {}, languageMatch[1]?.trim() ?? '') : null;
  }

  querySelector(selector: string): TestElement | null {
    if (selector === 'parsererror') return null;
    if (selector === 'rootfile') return this.rootfile;
    if (selector === 'spine') return this.spineElement;
    if (selector.startsWith('metadata title') || selector.startsWith('metadata dc\\:title')) return this.title;
    if (selector.startsWith('metadata language') || selector.startsWith('metadata dc\\:language')) return this.language;
    if (selector === 'metadata meta[property="rendition:layout"]') return null;
    if (selector === 'head') return new TestElement('head');
    return null;
  }

  querySelectorAll(selector: string): readonly TestElement[] {
    if (selector === 'manifest > item') return this.manifestItems;
    if (selector === 'spine > itemref') return this.spineItems;
    return [];
  }

  createElementNS(_namespace: string, name: string): TestElement { return new TestElement(name); }
}

class TestDomParser {
  parseFromString(source: string, _mimeType: string): TestDocument { return new TestDocument(source); }
}

class TestXmlSerializer {
  serializeToString(document: TestDocument): string { return document.serialized; }
}

function installDomStubs(): () => void {
  const previous = new Map<string, unknown>();
  for (const [name, value] of [['DOMParser', TestDomParser], ['XMLSerializer', TestXmlSerializer]] as const) {
    previous.set(name, Reflect.get(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, value });
  }
  return () => {
    for (const [name, value] of previous) {
      if (value === undefined) delete (globalThis as unknown as Record<string, unknown>)[name];
      else Object.defineProperty(globalThis, name, { configurable: true, value });
    }
  };
}

function encodeWindows1251(source: string): Uint8Array {
  const encoded = new Uint8Array(source.length);
  for (let index = 0; index < source.length; index += 1) {
    const codePoint = source.charCodeAt(index);
    const byte = codePoint <= 0x7f
      ? codePoint
      : codePoint >= 0x410 && codePoint <= 0x44f
        ? (codePoint <= 0x42f ? 0xc0 : 0xe0) + (codePoint - (codePoint <= 0x42f ? 0x410 : 0x430))
        : null;
    if (byte === null) throw new Error(`Test encoder does not support U+${codePoint.toString(16)}`);
    encoded[index] = byte;
  }
  return encoded;
}

async function epubBlob(entries: readonly Readonly<{ path: string; bytes: Uint8Array | string }>[] = []): Promise<Blob> {
  const writer = new ZipWriter(new BlobWriter('application/epub+zip'), { useWebWorkers: false });
  await writer.add('mimetype', new TextReader('application/epub+zip'), { level: 0 });
  for (const entry of entries) {
    await writer.add(
      entry.path,
      typeof entry.bytes === 'string' ? new TextReader(entry.bytes) : new Uint8ArrayReader(entry.bytes),
      { level: 0 }
    );
  }
  return writer.close();
}

class FakeMobiWorker {
  static result: MobiOpenResult;
  static resources = new Map<number, Uint8Array>();
  private readonly listeners = new Map<string, Array<(event: MessageEvent<unknown>) => void>>();

  addEventListener(type: string, listener: (event: MessageEvent<unknown>) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  postMessage(request: MobiWorkerRequest): void {
    queueMicrotask(() => {
      const data = request.type === 'open'
        ? { requestId: request.requestId, ok: true, type: 'open', result: FakeMobiWorker.result }
        : request.type === 'read'
          ? { requestId: request.requestId, ok: true, type: 'read', bytes: FakeMobiWorker.resources.get(request.resourceIndex)?.slice().buffer }
          : { requestId: request.requestId, ok: true, type: 'close' };
      const event = { data } as MessageEvent<unknown>;
      for (const listener of this.listeners.get('message') ?? []) listener(event);
    });
  }

  terminate(): void {}
}

function installWorkerStub(): () => void {
  const previous = Reflect.get(globalThis, 'Worker');
  Object.defineProperty(globalThis, 'Worker', { configurable: true, value: FakeMobiWorker });
  return () => {
    if (previous === undefined) delete (globalThis as unknown as Record<string, unknown>).Worker;
    else Object.defineProperty(globalThis, 'Worker', { configurable: true, value: previous });
  };
}

function installChapterArtifactStubs(): () => void {
  const previousLocation = Reflect.get(globalThis, 'location');
  const previousFetch = globalThis.fetch;
  const artifactFiles = new Map<string, string>([
    ['artifact-manifest.json', 'application/json'],
    ['ermao-chapters.wasm', 'application/wasm']
  ]);
  Object.defineProperty(globalThis, 'location', {
    configurable: true,
    value: new URL('http://reader.test/')
  });
  globalThis.fetch = async (input) => {
    const requestUrl = new URL(
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
      'http://reader.test/'
    );
    const fileName = requestUrl.pathname.split('/vendor/chapter-core/')[1] ?? '';
    const contentType = artifactFiles.get(fileName);
    if (!contentType) throw new Error(`TEST_UNEXPECTED_ARTIFACT_REQUEST:${requestUrl.pathname}`);
    const bytes = await readFile(path.join(chapterArtifactRoot, fileName));
    return new Response(bytes, { status: 200, headers: { 'Content-Type': contentType } });
  };
  return () => {
    globalThis.fetch = previousFetch;
    if (previousLocation === undefined) delete (globalThis as unknown as Record<string, unknown>).location;
    else Object.defineProperty(globalThis, 'location', { configurable: true, value: previousLocation });
  };
}

test('EPUB archive paths normalize safe dot and separator segments while blocking escape', () => {
  assert.equal(normalizeEpubArchivePath('OPS/./text/../chapter.xhtml'), 'OPS/chapter.xhtml');
  assert.equal(normalizeEpubArchivePath('OPS\\text\\chapter.xhtml'), 'OPS/text/chapter.xhtml');
  assert.throws(
    () => normalizeEpubArchivePath('../outside.xhtml'),
    /PUBLICATION_SECURITY_REJECTED/
  );
});

function findBytes(haystack: Uint8Array, needle: Uint8Array): number {
  outer: for (let offset = 0; offset <= haystack.length - needle.length; offset += 1) {
    for (let index = 0; index < needle.length; index += 1) {
      if (haystack[offset + index] !== needle[index]) continue outer;
    }
    return offset;
  }
  return -1;
}

function replaceZipCompressionMethod(bytes: Uint8Array, method: number): void {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let replacements = 0;
  for (let offset = 0; offset <= bytes.byteLength - 12; offset += 1) {
    const signature = view.getUint32(offset, true);
    if (signature === 0x04034b50) {
      view.setUint16(offset + 8, method, true);
      replacements += 1;
    } else if (signature === 0x02014b50) {
      view.setUint16(offset + 10, method, true);
      replacements += 1;
    }
  }
  assert.equal(replacements, 2);
}

test('EPUB metadata preflight defers CRC failure until an archive entry is read', async () => {
  const payload = 'unused-entry-crc-payload';
  const writer = new ZipWriter(new BlobWriter('application/epub+zip'), { useWebWorkers: false });
  await writer.add('unused.bin', new TextReader(payload), { level: 0 });
  const archive = await writer.close();
  const bytes = new Uint8Array(await archive.arrayBuffer());
  const payloadOffset = findBytes(bytes, new TextEncoder().encode(payload));
  assert.notEqual(payloadOffset, -1);
  bytes[payloadOffset] = (bytes[payloadOffset] ?? 0) ^ 0x01;

  const reader = new ZipReader(new BlobReader(
    new Blob([Uint8Array.from(bytes).buffer], { type: 'application/epub+zip' })
  ));
  try {
    const entries = await reader.getEntries({ strictness: 'strict', filenameValidation: 'strict' });
    const result = await preflightEpubArchiveEntries(entries);
    const entry = result.entries.get('unused.bin');
    assert.ok(entry);
    await assert.rejects(
      readEpubArchiveEntry(entry, false),
      /PUBLICATION_RESOURCE_BLOCKED/
    );
  } finally {
    await reader.close();
  }
});

test('EPUB preflight reports an unavailable compression algorithm as an engine failure', async () => {
  const writer = new ZipWriter(new BlobWriter('application/epub+zip'), { useWebWorkers: false });
  await writer.add('unused.bin', new TextReader('unsupported-compression'), { level: 0 });
  const archive = await writer.close();
  const bytes = new Uint8Array(await archive.arrayBuffer());
  replaceZipCompressionMethod(bytes, 99);

  const reader = new ZipReader(new BlobReader(
    new Blob([Uint8Array.from(bytes).buffer], { type: 'application/epub+zip' })
  ));
  try {
    const entries = await reader.getEntries({ strictness: 'strict', filenameValidation: 'strict' });
    const result = await preflightEpubArchiveEntries(entries);
    const entry = result.entries.get('unused.bin');
    assert.ok(entry);
    await assert.rejects(
      readEpubArchiveEntry(entry, true),
      (reason: unknown) => reason instanceof ReaderSafetyImplementationError
        && reason.ruleId === READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE
        && reason.code.startsWith('ENGINE_')
        && (READER_SAFETY_IMPLEMENTATION_FAILURE_CODES as readonly string[]).includes(reason.code)
    );
  } finally {
    await reader.close();
  }
});

test('openEpub decodes declared XML encodings before the first reading-order read', async () => {
  const restoreDom = installDomStubs();
  try {
    const container = '<?xml version="1.0" encoding="UTF-8"?><container><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>';
    const opf = '<?xml version="1.0" encoding="windows-1251"?><package><metadata><dc:title>Тест</dc:title></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chapter"/></spine></package>';
    const chapter = '<?xml version="1.0" encoding="UTF-8"?><html><body>Chapter text</body></html>';
    const publication = await openReadiumPublication(
      await epubBlob([
        { path: 'META-INF/container.xml', bytes: container },
        { path: 'OPS/content.opf', bytes: encodeWindows1251(opf) },
        { path: 'OPS/chapter.xhtml', bytes: chapter }
      ]),
      'epub',
      'Fallback',
      'ltr',
      'horizontal'
    );
    try {
      assert.equal(publication.publication.metadata.title.getTranslation('und'), 'Тест');
      const chapterLink = publication.publication.readingOrder.items[0];
      assert.ok(chapterLink);
      const firstRead = await publication.publication.get(chapterLink).read();
      assert.match(new TextDecoder().decode(firstRead), /Chapter text/u);
    } finally {
      publication.close();
    }
  } finally {
    restoreDom();
  }
});

test('openEpub rejects invalid required control XML as publication integrity', async () => {
  const restoreDom = installDomStubs();
  try {
    const validPrefix = new TextEncoder().encode('<?xml version="1.0" encoding="UTF-8"?><container><rootfiles>');
    const invalidContainer = new Uint8Array(validPrefix.byteLength + 1);
    invalidContainer.set(validPrefix);
    invalidContainer[invalidContainer.length - 1] = 0xff;
    await assert.rejects(
      openReadiumPublication(
        await epubBlob([{ path: 'META-INF/container.xml', bytes: invalidContainer }]),
        'epub',
        'Fallback',
        'ltr',
        'horizontal'
      ),
      (reason: unknown) => reason instanceof ReaderSafetyPolicyError
        && reason.ruleId === READER_SAFETY_RULE_IDS.EPUB_RESOURCE_INTEGRITY
        && reason.code === 'PUBLICATION_CORRUPT'
    );
  } finally {
    restoreDom();
  }
});

test('openEpub isolates a corrupt optional CSS resource until its first read', async () => {
  const restoreDom = installDomStubs();
  try {
    const container = '<?xml version="1.0" encoding="UTF-8"?><container><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>';
    const opf = '<?xml version="1.0" encoding="UTF-8"?><package><metadata><dc:title>Optional CSS</dc:title></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="style" href="style.css" media-type="text/css"/></manifest><spine><itemref idref="chapter"/></spine></package>';
    const chapter = '<?xml version="1.0" encoding="UTF-8"?><html><body>Chapter text</body></html>';
    const style = new TextEncoder().encode('body { color: red; unique-crc-marker: 7; }');
    const archive = new Uint8Array(await (await epubBlob([
      { path: 'META-INF/container.xml', bytes: container },
      { path: 'OPS/content.opf', bytes: opf },
      { path: 'OPS/chapter.xhtml', bytes: chapter },
      { path: 'OPS/style.css', bytes: style }
    ])).arrayBuffer());
    const styleOffset = findBytes(archive, style);
    assert.notEqual(styleOffset, -1);
    archive[styleOffset] = (archive[styleOffset] ?? 0) ^ 0x01;
    const publication = await openReadiumPublication(
      new Blob([Uint8Array.from(archive).buffer], { type: 'application/epub+zip' }),
      'epub',
      'Fallback',
      'ltr',
      'horizontal'
    );
    try {
      const chapterLink = publication.publication.readingOrder.items[0];
      assert.ok(chapterLink);
      assert.match(new TextDecoder().decode(await publication.publication.get(chapterLink).read()), /Chapter text/u);
      const cssLink = publication.publication.resources?.items.find((link) => link.href === 'OPS/style.css');
      assert.ok(cssLink);
      await assert.rejects(
        publication.publication.get(cssLink).read(),
        (reason: unknown) => reason instanceof ReaderSafetyPolicyError
          && reason.ruleId === READER_SAFETY_RULE_IDS.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE
          && reason.code === 'PUBLICATION_RESOURCE_BLOCKED'
      );
    } finally {
      publication.close();
    }
  } finally {
    restoreDom();
  }
});

test('openMobi sanitizes extra CSS resources on their first read', async () => {
  const restoreDom = installDomStubs();
  const restoreWorker = installWorkerStub();
  const restoreChapterArtifacts = installChapterArtifactStubs();
  try {
    const chapter = new TextEncoder().encode('<html><body>Chapter text</body></html>');
    const css = new TextEncoder().encode('body { behavior: url(http://example.invalid/evil.htc); color: red; }');
    FakeMobiWorker.result = {
      title: 'MOBI test',
      language: 'en',
      readingOrder: [1],
      toc: [{ title: 'Chapter', resourceIndex: 1, fragment: null, parentIndex: null }],
      resources: [
        { index: 1, category: 0, sourceName: 'chapter.xhtml', mediaType: 'application/xhtml+xml', decodedLength: chapter.byteLength },
        { index: 2, category: 1, sourceName: 'styles.css', mediaType: 'text/css', decodedLength: css.byteLength }
      ]
    };
    FakeMobiWorker.resources = new Map([[1, chapter], [2, css]]);
    const publication = await openMobiPublication(
      new Blob(),
      'mobi',
      'Fallback',
      'ltr',
      'horizontal'
    );
    try {
      const cssLink = publication.publication.resources?.items.find((link) => link.href === 'mobi/resource-2');
      assert.ok(cssLink);
      const firstRead = new TextDecoder().decode(await publication.publication.get(cssLink).read());
      assert.doesNotMatch(firstRead, /behavior\s*:/iu);
      assert.match(firstRead, /color\s*:\s*red/iu);
    } finally {
      publication.close();
    }
  } finally {
    restoreChapterArtifacts();
    restoreWorker();
    restoreDom();
  }
});
