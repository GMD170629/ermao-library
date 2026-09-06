import { BlobReader, ZipReader, type FileEntry } from '@zip.js/zip.js';
import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_RULE_IDS,
  type ReaderReadingProgression,
  type ReaderWritingMode,
  type ReflowableFormat
} from '@shuku/reader-core';
import { openMobiPublication } from '../original-publication/mobi-publication';
import {
  createLocalPublication,
  type LocalPublicationTocEntry,
  type ReadiumPublication
} from '../original-publication/local-publication';
import {
  chapterEntriesToToc,
  parseXmlWithChapterCore,
  type ChapterXmlEvent
} from '../original-publication/chapter-core';
import { openTextPublication } from '../original-publication/text-publication';
import {
  authoredUriDisposition,
  preflightReflowableXml,
  rejectReaderSafety,
  ReaderSafetyPolicyError,
  rewriteAuthoredDocumentReferences,
  sanitizeAuthoredCss,
  sanitizeAuthoredMarkup
} from '../security/reader-safety-policy';
import {
  normalizeEpubArchivePath,
  preflightEpubArchiveEntries,
  readEpubArchiveEntry,
  rejectEpubResourceReadFailure,
  rejectUnreadableEpubResource
} from '../security/epub-archive-safety';

const MAX_XML_BYTES = READER_SAFETY_BUDGETS.xmlControlDocumentMaxBytes;

function bareHref(href: string): string {
  return href.split('#', 1)[0]?.split('?', 1)[0] ?? href;
}

const EPUB_TYPE_NAMESPACE = 'http://www.idpf.org/2007/ops';
const NCX_MEDIA_TYPE = 'application/x-dtbncx+xml';

type EpubManifestItem = Readonly<{
  path: string;
  type: string;
  properties: string;
}>;

function localName(element: Element): string {
  return (element.localName || element.tagName).toLowerCase();
}

function fragmentOf(href: string): string {
  const hash = href.indexOf('#');
  return hash >= 0 ? href.slice(hash) : '';
}

function navigationHref(
  rawHref: string,
  sourcePath: string,
  knownManifestPaths: ReadonlySet<string>
): string | null {
  const trimmed = rawHref.trim();
  const path = trimmed.startsWith('#') ? sourcePath : resolveArchivePath(sourcePath, trimmed);
  if (!path || !knownManifestPaths.has(path)) return null;
  return `${path}${fragmentOf(trimmed)}`;
}

function chapterXmlEvents(
  root: Node,
  sourcePath: string,
  knownManifestPaths: ReadonlySet<string>,
  format: 'epub-nav' | 'epub-ncx'
): ChapterXmlEvent[] {
  const events: ChapterXmlEvent[] = [];
  const visit = (node: Node): void => {
    if (node.nodeType === 3 || node.nodeType === 4) {
      const text = node.nodeValue ?? '';
      if (text) events.push({ kind: 'text', text });
      return;
    }
    if (node.nodeType !== 1) return;
    const element = node as Element;
    const name = element.localName || element.tagName;
    const rawHref = format === 'epub-nav'
      ? localName(element) === 'a' ? element.getAttribute('href') : null
      : localName(element) === 'content' ? element.getAttribute('src') : null;
    const targetHref = rawHref === null
      ? undefined
      : navigationHref(rawHref ?? '', sourcePath, knownManifestPaths);
    events.push({
      kind: 'start',
      name,
      attributes: Array.from(element.attributes).map((attribute) => ({
        // The chapter ABI intentionally uses local semantic names. EPUB's
        // namespaced epub:type is the same nav discriminator as type.
        name: attribute.name.toLowerCase() === 'epub:type'
          || attribute.localName === 'type' && attribute.namespaceURI === EPUB_TYPE_NAMESPACE
          ? 'type'
          : attribute.name,
        value: attribute.value
      })),
      ...(rawHref === null ? {} : { targetHref })
    });
    for (const child of Array.from(element.childNodes)) visit(child);
    events.push({ kind: 'end', name });
  };
  visit(root);
  return events;
}

async function parseEpubNavigationWithChapterCore(
  document: XMLDocument,
  sourcePath: string,
  knownManifestPaths: ReadonlySet<string>,
  format: 'epub-nav' | 'epub-ncx'
): Promise<LocalPublicationTocEntry[]> {
  const result = await parseXmlWithChapterCore(
    format,
    chapterXmlEvents(document.documentElement, sourcePath, knownManifestPaths, format)
  );
  return chapterEntriesToToc(result.entries);
}

function titleByTocPath(entries: readonly LocalPublicationTocEntry[]): Map<string, string> {
  const titles = new Map<string, string>();
  const visit = (items: readonly LocalPublicationTocEntry[]) => {
    for (const item of items) {
      if (item.href) titles.set(bareHref(item.href), item.title);
      if (item.children) visit(item.children);
    }
  };
  visit(entries);
  return titles;
}

/** Applies the adapter's deterministic EPUB navigation precedence. */
export function resolveEpubNavigation(
  epub3: readonly LocalPublicationTocEntry[],
  ncx: readonly LocalPublicationTocEntry[]
): LocalPublicationTocEntry[] {
  if (epub3.length > 0) return [...epub3];
  if (ncx.length > 0) return [...ncx];
  return [];
}

/** Resolves the NCX through the OPF spine's declared ID, with a safe typed fallback. */
export function resolveEpub2NcxManifestItem(
  manifestItems: ReadonlyMap<string, EpubManifestItem>,
  spineTocId: string | null | undefined
): EpubManifestItem | null {
  const declaredId = spineTocId?.trim();
  const declaredItem = declaredId ? manifestItems.get(declaredId) : null;
  if (declaredItem) return declaredItem;
  return [...manifestItems.values()].find((item) => item.type.toLowerCase() === NCX_MEDIA_TYPE) ?? null;
}

function utf8(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

type XmlEncoding = Readonly<{
  label: string;
  offset: number;
}>;

function byteSequenceStartsWith(bytes: Uint8Array, offset: number, sequence: readonly number[]): boolean {
  return sequence.every((value, index) => bytes[offset + index] === value);
}

function xmlEncoding(bytes: Uint8Array): XmlEncoding {
  let label = 'utf-8';
  let offset = 0;
  let closeSequence: readonly number[] = [0x3f, 0x3e];
  let declarationPrefix: readonly number[] = [0x3c, 0x3f, 0x78, 0x6d, 0x6c];
  if (byteSequenceStartsWith(bytes, 0, [0xef, 0xbb, 0xbf])) {
    offset = 3;
  } else if (byteSequenceStartsWith(bytes, 0, [0xff, 0xfe])) {
    label = 'utf-16le';
    offset = 2;
    closeSequence = [0x3f, 0x00, 0x3e, 0x00];
    declarationPrefix = [0x3c, 0x00, 0x3f, 0x00, 0x78, 0x00, 0x6d, 0x00, 0x6c, 0x00];
  } else if (byteSequenceStartsWith(bytes, 0, [0xfe, 0xff])) {
    label = 'utf-16be';
    offset = 2;
    closeSequence = [0x00, 0x3f, 0x00, 0x3e];
    declarationPrefix = [0x00, 0x3c, 0x00, 0x3f, 0x00, 0x78, 0x00, 0x6d, 0x00, 0x6c];
  } else if (byteSequenceStartsWith(bytes, 0, [0x00, 0x3c, 0x00, 0x3f])) {
    label = 'utf-16be';
    closeSequence = [0x00, 0x3f, 0x00, 0x3e];
    declarationPrefix = [0x00, 0x3c, 0x00, 0x3f, 0x00, 0x78, 0x00, 0x6d, 0x00, 0x6c];
  } else if (byteSequenceStartsWith(bytes, 0, [0x3c, 0x00, 0x3f, 0x00])) {
    label = 'utf-16le';
    closeSequence = [0x3f, 0x00, 0x3e, 0x00];
    declarationPrefix = [0x3c, 0x00, 0x3f, 0x00, 0x78, 0x00, 0x6d, 0x00, 0x6c, 0x00];
  }
  if (!byteSequenceStartsWith(bytes, offset, declarationPrefix)) {
    return { label, offset };
  }
  let declarationEnd: number | null = null;
  for (let index = offset + declarationPrefix.length; index <= bytes.length - closeSequence.length; index += 1) {
    if (byteSequenceStartsWith(bytes, index, closeSequence)) {
      declarationEnd = index + closeSequence.length;
      break;
    }
  }
  if (declarationEnd === null) return { label, offset };
  const declaration = new TextDecoder(label, { fatal: true }).decode(bytes.subarray(offset, declarationEnd));
  const declared = /\bencoding\s*=\s*(['"])([^'"]+)\1/iu.exec(declaration)?.[2]?.trim();
  if (declared) {
    const normalized = declared.toLowerCase();
    label = normalized === 'utf-16' ? label : declared;
  }
  return { label, offset };
}

function decodeXml(bytes: Uint8Array, requiredResource: boolean): string {
  try {
    const encoding = xmlEncoding(bytes);
    return new TextDecoder(encoding.label, { fatal: true })
      .decode(bytes.subarray(encoding.offset))
      .replace(/^\uFEFF/u, '');
  } catch (cause) {
    rejectEpubResourceReadFailure(cause, requiredResource);
  }
}

function parseXml(
  value: string,
  code: string,
  maxBytes: number = READER_SAFETY_BUDGETS.reflowableMarkupMaxBytes,
  maxBytesRuleId: typeof READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES
    | typeof READER_SAFETY_RULE_IDS.REFLOWABLE_MARKUP_MAX_BYTES = READER_SAFETY_RULE_IDS.REFLOWABLE_MARKUP_MAX_BYTES,
  requiredResource = true
): XMLDocument {
  const safeSource = preflightReflowableXml(
    value,
    maxBytes,
    maxBytesRuleId
  );
  const document = new DOMParser().parseFromString(safeSource, 'application/xml');
  if (document.querySelector('parsererror')) {
    rejectEpubResourceReadFailure(new Error(code), requiredResource);
  }
  return document;
}

function publicationTextLength(bytes: Uint8Array): number {
  if (bytes.byteLength > READER_SAFETY_BUDGETS.reflowableMarkupMaxBytes) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_MARKUP_MAX_BYTES);
  }
  const source = decodeXml(bytes, true);
  const document = parseXml(source, 'PUBLICATION_MARKUP_INVALID');
  return Math.max(1, (document.body?.textContent ?? document.documentElement.textContent ?? '').length);
}

function resolveArchivePath(base: string, relative: string): string | null {
  const trimmed = relative.trim();
  if (!trimmed || trimmed.startsWith('#')) return null;
  if (authoredUriDisposition(trimmed, 'subresource') === 'remove') return null;
  const path = bareHref(trimmed);
  const baseSegments = base.split('/').slice(0, -1);
  for (const segment of path.split('/')) {
    if (!segment || segment === '.') continue;
    if (segment === '..') {
      if (baseSegments.length === 0) rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE);
      baseSegments.pop();
    } else {
      baseSegments.push(segment);
    }
  }
  return normalizeEpubArchivePath(baseSegments.join('/'));
}

async function readZipEntry(
  entry: FileEntry,
  signal: AbortSignal | undefined,
  requiredResource: boolean
): Promise<Uint8Array> {
  return readEpubArchiveEntry(entry, requiredResource, signal);
}

async function rewriteCssUrls(
  source: string,
  href: string,
  assetUrl: (path: string, ancestors?: ReadonlySet<string>) => Promise<string | null>,
  ancestors: ReadonlySet<string>
): Promise<string> {
  return sanitizeAuthoredCss(source, async (raw) => {
    const resolved = resolveArchivePath(href, raw);
    return resolved ? assetUrl(resolved, ancestors) : null;
  });
}

async function sanitizeEpubDocument(
  bytes: Uint8Array,
  href: string,
  assetUrl: (path: string) => Promise<string | null>
): Promise<Uint8Array> {
  if (bytes.byteLength > READER_SAFETY_BUDGETS.reflowableMarkupMaxBytes) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_MARKUP_MAX_BYTES);
  }
  const source = decodeXml(bytes, true);
  const document = parseXml(source, 'PUBLICATION_MARKUP_INVALID');
  sanitizeAuthoredMarkup(document);
  await rewriteAuthoredDocumentReferences(document, async (raw) => {
    const resolved = resolveArchivePath(href, raw);
    return resolved ? assetUrl(resolved) : null;
  });
  return utf8(new XMLSerializer().serializeToString(document));
}

async function openEpub(
  blob: Blob,
  fallbackTitle: string,
  readingProgression: ReaderReadingProgression,
  writingMode: ReaderWritingMode,
  signal?: AbortSignal
): Promise<ReadiumPublication> {
  const reader = new ZipReader(new BlobReader(blob), { strictness: 'strict', checkOverlappingEntry: true });
  const objectUrls = new Set<string>();
  try {
    const rawEntries = await reader.getEntries({ strictness: 'strict', filenameValidation: 'strict' });
    const archive = await preflightEpubArchiveEntries(rawEntries, signal);
    const byPath = archive.entries;
    const required = (path: string) => {
      const entry = byPath.get(path);
      if (!entry) {
        if (archive.unreadablePaths.has(path)) {
          rejectUnreadableEpubResource();
        }
        throw new Error('PUBLICATION_STRUCTURE_INVALID');
      }
      return entry;
    };
    const isOptionalNavigationFailure = (cause: unknown): boolean => {
      if (cause instanceof ReaderSafetyPolicyError) {
        return cause.ruleId === READER_SAFETY_RULE_IDS.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE;
      }
      return cause instanceof Error
        && (cause.message === 'PUBLICATION_STRUCTURE_INVALID'
          || cause.message === 'PUBLICATION_MARKUP_INVALID');
    };
    // The mimetype entry is read as part of the original package control
    // path, while its authored value remains metadata. Actual archive and
    // parser failures are classified at the concrete read/parse boundary.
    await readZipEntry(required('mimetype'), signal, true);
    const containerBytes = await readZipEntry(required('META-INF/container.xml'), signal, true);
    if (containerBytes.byteLength > MAX_XML_BYTES) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES);
    }
    const container = parseXml(
      decodeXml(containerBytes, true),
      'PUBLICATION_STRUCTURE_INVALID',
      MAX_XML_BYTES,
      READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES
    );
    const rootfile = container.querySelector('rootfile')?.getAttribute('full-path');
    if (!rootfile) throw new Error('PUBLICATION_STRUCTURE_INVALID');
    const opfPath = normalizeEpubArchivePath(rootfile);
    const opfBytes = await readZipEntry(required(opfPath), signal, true);
    if (opfBytes.byteLength > MAX_XML_BYTES) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES);
    }
    const opf = parseXml(
      decodeXml(opfBytes, true),
      'PUBLICATION_STRUCTURE_INVALID',
      MAX_XML_BYTES,
      READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES
    );
    const manifestItems = new Map<string, EpubManifestItem>();
    for (const item of opf.querySelectorAll('manifest > item')) {
      const id = item.getAttribute('id');
      const href = item.getAttribute('href');
      const type = item.getAttribute('media-type')?.split(';', 1)[0]?.trim().toLowerCase() ?? '';
      if (!id || !href) continue;
      const path = resolveArchivePath(opfPath, href);
      if (!path || !byPath.has(path)) continue;
      manifestItems.set(id, {
        path,
        type,
        properties: item.getAttribute('properties') ?? ''
      });
    }
    const knownManifestPaths = new Set([...manifestItems.values()].map((item) => item.path));
    const navItem = [...manifestItems.values()].find((item) => item.properties.split(/\s+/).includes('nav'));
    let epub3Toc: LocalPublicationTocEntry[] = [];
    if (navItem) {
      const navEntry = byPath.get(navItem.path);
      if (navEntry) {
        if (navEntry.uncompressedSize > MAX_XML_BYTES) {
          rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES);
        }
        try {
          const nav = parseXml(
            decodeXml(await readZipEntry(navEntry, signal, false), false),
            'PUBLICATION_STRUCTURE_INVALID',
            MAX_XML_BYTES,
            READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES,
            false
          );
          epub3Toc = await parseEpubNavigationWithChapterCore(
            nav,
            navItem.path,
            knownManifestPaths,
            'epub-nav'
          );
        } catch (cause) {
          if (!isOptionalNavigationFailure(cause)) throw cause;
        }
      }
    }
    let ncxToc: LocalPublicationTocEntry[] = [];
    if (epub3Toc.length === 0) {
      const spineTocId = opf.querySelector('spine')?.getAttribute('toc');
      const ncxItem = resolveEpub2NcxManifestItem(manifestItems, spineTocId);
      if (ncxItem) {
        const ncxEntry = byPath.get(ncxItem.path);
        if (ncxEntry) {
          if (ncxEntry.uncompressedSize > MAX_XML_BYTES) {
            rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES);
          }
          try {
            const ncx = parseXml(
              decodeXml(await readZipEntry(ncxEntry, signal, false), false),
              'PUBLICATION_STRUCTURE_INVALID',
              MAX_XML_BYTES,
              READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES,
              false
            );
            ncxToc = await parseEpubNavigationWithChapterCore(
              ncx,
              ncxItem.path,
              knownManifestPaths,
              'epub-ncx'
            );
          } catch (cause) {
            if (!isOptionalNavigationFailure(cause)) throw cause;
          }
        }
      }
    }
    const authoredToc = resolveEpubNavigation(epub3Toc, ncxToc);
    const titleByPath = titleByTocPath(authoredToc);
    const itemByPath = new Map([...manifestItems.values()].map((item) => [item.path, item]));
    // Spine membership is the authoritative role for reading-order markup.
    // A declared media type is metadata and must not bypass the in-memory XML
    // sanitizer for an otherwise readable chapter.
    const spinePaths = new Set<string>();
    for (const itemref of opf.querySelectorAll('spine > itemref')) {
      const item = manifestItems.get(itemref.getAttribute('idref') ?? '');
      if (item) spinePaths.add(item.path);
    }
    const rawReads = new Map<string, Promise<Uint8Array>>();
    const resourceReads = new Map<string, Promise<Uint8Array>>();
    const assetUrls = new Map<string, Promise<string | null>>();
    const rawBytes = (path: string, requiredResource: boolean): Promise<Uint8Array> => {
      const existing = rawReads.get(path);
      if (existing) return existing;
      let entry = byPath.get(path);
      if (!entry && requiredResource) entry = required(path);
      if (!entry) {
        if (archive.unreadablePaths.has(path)) {
          rejectEpubResourceReadFailure(new Error('PUBLICATION_RESOURCE_UNREADABLE'), false);
        }
        throw new Error('PUBLICATION_RESOURCE_NOT_FOUND');
      }
      const pending = readZipEntry(entry, signal, requiredResource);
      rawReads.set(path, pending);
      return pending;
    };
    const assetUrl = (path: string, ancestors: ReadonlySet<string> = new Set()): Promise<string | null> => {
      // Reading-order documents are parsed through resourceBytes and are
      // never exposed as subresources merely because their MIME is unknown.
      if (ancestors.has(path) || spinePaths.has(path) || !itemByPath.has(path)) return Promise.resolve(null);
      const existing = assetUrls.get(path);
      if (existing) return existing;
      const pending = (async () => {
        try {
          const item = itemByPath.get(path);
          if (!item || spinePaths.has(path)) return null;
          const nextAncestors = new Set(ancestors);
          nextAncestors.add(path);
          const bytes = await resourceBytes(path, nextAncestors);
          const url = URL.createObjectURL(new Blob([Uint8Array.from(bytes).buffer], { type: item.type }));
          objectUrls.add(url);
          return url;
        } catch (cause) {
          if (cause instanceof ReaderSafetyPolicyError && cause.action === 'BLOCK_RESOURCE') {
            return null;
          }
          throw cause;
        }
      })();
      assetUrls.set(path, pending);
      return pending;
    };
    const resourceBytes = (path: string, ancestors: ReadonlySet<string> = new Set()): Promise<Uint8Array> => {
      const existing = resourceReads.get(path);
      if (existing) return existing;
      const pending = (async () => {
        const item = itemByPath.get(path);
        if (!item) throw new Error('PUBLICATION_RESOURCE_NOT_FOUND');
        const bytes = await rawBytes(path, spinePaths.has(path));
        if (spinePaths.has(path)) return sanitizeEpubDocument(bytes, path, assetUrl);
        const nextAncestors = new Set(ancestors);
        nextAncestors.add(path);
        if (item.type === 'text/css') {
          let source: string;
          try {
            source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
          } catch (cause) {
            rejectEpubResourceReadFailure(cause, false);
          }
          return utf8(await rewriteCssUrls(
            source,
            path,
            assetUrl,
            nextAncestors
          ));
        }
        if (item.type === 'image/svg+xml') {
          const svg = parseXml(
            decodeXml(bytes, false),
            'PUBLICATION_MARKUP_INVALID',
            READER_SAFETY_BUDGETS.reflowableMarkupMaxBytes,
            READER_SAFETY_RULE_IDS.REFLOWABLE_MARKUP_MAX_BYTES,
            false
          );
          sanitizeAuthoredMarkup(svg);
          await rewriteAuthoredDocumentReferences(svg, async (raw) => {
            const resolved = resolveArchivePath(path, raw);
            return resolved ? assetUrl(resolved, nextAncestors) : null;
          });
          return utf8(new XMLSerializer().serializeToString(svg));
        }
        return bytes;
      })();
      resourceReads.set(path, pending);
      return pending;
    };
    const readingOrder: Array<{
      href: string;
      type: string;
      title: string;
      size: number;
      positionLength: number;
      read: () => Promise<Uint8Array>;
    }> = [];
    const readingOrderPaths = new Set<string>();
    for (const itemref of opf.querySelectorAll('spine > itemref')) {
      const item = manifestItems.get(itemref.getAttribute('idref') ?? '');
      const itemId = itemref.getAttribute('idref') ?? '';
      if (!item) {
        const rawManifestItem = [...opf.querySelectorAll('manifest > item')].find(
          (candidate) => candidate.getAttribute('id') === itemId
        );
        const rawHref = rawManifestItem?.getAttribute('href');
        const missingPath = rawHref ? resolveArchivePath(opfPath, rawHref) : null;
        if (missingPath && archive.unreadablePaths.has(missingPath)) {
          rejectUnreadableEpubResource();
        }
      }
      if (!item) continue;
      const entry = required(item.path);
      const normalizedBytes = await resourceBytes(item.path);
      const positionLength = publicationTextLength(normalizedBytes);
      readingOrderPaths.add(item.path);
      readingOrder.push({
        href: item.path,
        type: item.type,
        title: titleByPath.get(item.path) ?? item.path.split('/').pop() ?? item.path,
        size: entry.uncompressedSize,
        positionLength,
        read: () => resourceBytes(item.path)
      });
    }
    if (readingOrder.length === 0) throw new Error('PUBLICATION_STRUCTURE_INVALID');
    const toc = resolveEpubNavigation(epub3Toc, ncxToc);
    const extraResources = [...manifestItems.values()]
      .filter((item) => !readingOrderPaths.has(item.path))
      .map((item) => ({
        href: item.path,
        type: item.type,
        size: required(item.path).uncompressedSize,
        read: () => resourceBytes(item.path)
      }));
    const title = opf.querySelector('metadata title, metadata dc\\:title')?.textContent?.trim() || fallbackTitle;
    const language = opf.querySelector('metadata language, metadata dc\\:language')?.textContent?.trim() || null;
    const renditionLayout = opf.querySelector('metadata meta[property="rendition:layout"]')?.textContent?.trim();
    return createLocalPublication({
      title,
      language,
      readingProgression,
      writingMode,
      layout: renditionLayout === 'pre-paginated' ? 'fixed' : 'reflowable',
      readingOrder,
      toc,
      extraResources,
      onClose: () => {
        for (const url of objectUrls) URL.revokeObjectURL(url);
        void reader.close().catch(() => undefined);
      }
    });
  } catch (cause) {
    for (const url of objectUrls) URL.revokeObjectURL(url);
    await reader.close().catch(() => undefined);
    throw cause;
  }
}

/** Opens a complete original publication; no server manifest, positions or chapter URL is consulted. */
export async function openReadiumPublication(
  blob: Blob,
  format: ReflowableFormat,
  title: string,
  readingProgression: ReaderReadingProgression,
  writingMode: ReaderWritingMode,
  signal?: AbortSignal
): Promise<ReadiumPublication> {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  if (format === 'epub') return openEpub(blob, title, readingProgression, writingMode, signal);
  if (format === 'txt' || format === 'fb2') {
    return openTextPublication(blob, format, title, readingProgression, writingMode, signal);
  }
  return openMobiPublication(blob, format, title, readingProgression, writingMode, signal);
}
