import { BlobReader, ZipReader, type FileEntry } from '@zip.js/zip.js';
import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_FORMATS,
  READER_SAFETY_PROFILES,
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
import { openTextPublication } from '../original-publication/text-publication';
import {
  authoredUriDisposition,
  preflightReflowableXml,
  rejectReaderSafety,
  rewriteAuthoredDocumentReferences,
  sanitizeAuthoredCss,
  sanitizeAuthoredMarkup
} from '../security/reader-safety-policy';
import {
  normalizeEpubArchivePath,
  preflightEpubArchiveEntries
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

function childElements(element: Element, name?: string): Element[] {
  const children = Array.from(element.children);
  if (!name) return children;
  const expected = name.toLowerCase();
  return children.filter((child) => localName(child) === expected);
}

function firstDescendant(element: Element, name: string): Element | null {
  const expected = name.toLowerCase();
  for (const child of childElements(element)) {
    if (localName(child) === expected) return child;
    const nested = firstDescendant(child, expected);
    if (nested) return nested;
  }
  return null;
}

function epubType(element: Element): string {
  return element.getAttribute('epub:type')
    ?? element.getAttributeNS(EPUB_TYPE_NAMESPACE, 'type')
    ?? '';
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
  const path = resolveArchivePath(sourcePath, rawHref);
  if (!path || !knownManifestPaths.has(path)) return null;
  return `${path}${fragmentOf(rawHref)}`;
}

function directNavigationAnchor(listItem: Element): Element | null {
  for (const child of childElements(listItem)) {
    const childName = localName(child);
    if (childName === 'ol' || childName === 'ul') break;
    if (childName === 'a' && child.hasAttribute('href')) return child;
    const nested = child.querySelector('a[href]');
    if (nested) return nested;
  }
  return null;
}

function parseNavigationList(
  list: Element,
  sourcePath: string,
  knownManifestPaths: ReadonlySet<string>
): LocalPublicationTocEntry[] {
  const entries: LocalPublicationTocEntry[] = [];
  for (const listItem of childElements(list, 'li')) {
    const anchor = directNavigationAnchor(listItem);
    const nestedList = childElements(listItem).find((child) => {
      const name = localName(child);
      return name === 'ol' || name === 'ul';
    });
    const children = nestedList
      ? parseNavigationList(nestedList, sourcePath, knownManifestPaths)
      : [];
    const label = anchor?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    const href = anchor?.getAttribute('href') ?? '';
    const resolvedHref = navigationHref(href, sourcePath, knownManifestPaths);
    if (!resolvedHref || !label) {
      entries.push(...children);
      continue;
    }
    entries.push({
      href: resolvedHref,
      title: label,
      ...(children.length > 0 ? { children } : {})
    });
  }
  return entries;
}

/** Parses the EPUB3 Navigation Document's `toc` nav while preserving nesting. */
export function parseEpub3Navigation(
  document: XMLDocument,
  sourcePath: string,
  knownManifestPaths: ReadonlySet<string>
): LocalPublicationTocEntry[] {
  const navs = Array.from(document.querySelectorAll('nav'));
  const tocNav = navs.find((nav) => epubType(nav).split(/\s+/).includes('toc'));
  if (!tocNav) return [];
  const list = childElements(tocNav).find((child) => {
    const name = localName(child);
    return name === 'ol' || name === 'ul';
  }) ?? firstDescendant(tocNav, 'ol') ?? firstDescendant(tocNav, 'ul');
  return list ? parseNavigationList(list, sourcePath, knownManifestPaths) : [];
}

function parseNcxNavPoint(
  navPoint: Element,
  sourcePath: string,
  knownManifestPaths: ReadonlySet<string>
): LocalPublicationTocEntry[] {
  const content = childElements(navPoint, 'content')[0];
  const rawHref = content?.getAttribute('src') ?? '';
  const href = navigationHref(rawHref, sourcePath, knownManifestPaths);
  const labelElement = childElements(navPoint, 'navlabel')[0];
  const label = firstDescendant(labelElement ?? navPoint, 'text')?.textContent
    ?.replace(/\s+/g, ' ').trim() ?? '';
  const children = childElements(navPoint, 'navpoint').flatMap((child) => (
    parseNcxNavPoint(child, sourcePath, knownManifestPaths)
  ));
  if (!href || !label) return children;
  return [{
    href,
    title: label,
    ...(children.length > 0 ? { children } : {})
  }];
}

/** Parses the EPUB2 NCX navigation map while preserving nested navPoints. */
export function parseEpub2NcxNavigation(
  document: XMLDocument,
  sourcePath: string,
  knownManifestPaths: ReadonlySet<string>
): LocalPublicationTocEntry[] {
  const navMap = firstDescendant(document.documentElement, 'navmap');
  if (!navMap) return [];
  return childElements(navMap, 'navpoint').flatMap((navPoint) => (
    parseNcxNavPoint(navPoint, sourcePath, knownManifestPaths)
  ));
}

function titleByTocPath(entries: readonly LocalPublicationTocEntry[]): Map<string, string> {
  const titles = new Map<string, string>();
  const visit = (items: readonly LocalPublicationTocEntry[]) => {
    for (const item of items) {
      titles.set(bareHref(item.href), item.title);
      if (item.children) visit(item.children);
    }
  };
  visit(entries);
  return titles;
}

/** Applies the adapter's deterministic EPUB navigation precedence. */
export function resolveEpubNavigation(
  epub3: readonly LocalPublicationTocEntry[],
  ncx: readonly LocalPublicationTocEntry[],
  readingOrder: readonly Readonly<{ href: string; title: string }>[]
): LocalPublicationTocEntry[] {
  if (epub3.length > 0) return [...epub3];
  if (ncx.length > 0) return [...ncx];
  return readingOrder.map((item) => ({ href: item.href, title: item.title }));
}

/** Resolves the NCX through the OPF spine's declared ID, with a safe typed fallback. */
export function resolveEpub2NcxManifestItem(
  manifestItems: ReadonlyMap<string, EpubManifestItem>,
  spineTocId: string | null | undefined
): EpubManifestItem | null {
  const declaredId = spineTocId?.trim();
  const declaredItem = declaredId ? manifestItems.get(declaredId) : null;
  if (declaredItem?.type.toLowerCase() === NCX_MEDIA_TYPE) return declaredItem;
  return [...manifestItems.values()].find((item) => item.type.toLowerCase() === NCX_MEDIA_TYPE) ?? null;
}

function utf8(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function parseXml(value: string, code: string): XMLDocument {
  const safeSource = preflightReflowableXml(value, READER_SAFETY_RULE_IDS.REFLOWABLE_REJECT_XML_ENTITY);
  const document = new DOMParser().parseFromString(safeSource, 'application/xml');
  if (document.querySelector('parsererror')) throw new Error(code);
  return document;
}

function publicationTextLength(bytes: Uint8Array): number {
  if (bytes.byteLength > READER_SAFETY_BUDGETS.reflowableMarkupMaxBytes) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_MARKUP_MAX_BYTES);
  }
  const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
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

async function readZipEntry(entry: FileEntry, signal?: AbortSignal): Promise<Uint8Array> {
  try {
    const buffer = await entry.arrayBuffer({ signal, strictness: 'strict', checkLocalDirectory: true, checkCrc32: true, checkOverlappingEntry: true });
    return new Uint8Array(buffer);
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    rejectReaderSafety(READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE, { cause });
  }
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
  const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
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
    const byPath = await preflightEpubArchiveEntries(rawEntries, signal);
    const required = (path: string) => {
      const entry = byPath.get(path);
      if (!entry) throw new Error('PUBLICATION_STRUCTURE_INVALID');
      return entry;
    };
    const mime = new TextDecoder().decode(await readZipEntry(required('mimetype'), signal)).trim();
    if (mime !== READER_SAFETY_FORMATS.EPUB.canonicalMimeType) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_EXACT_FORMAT_MIME);
    }
    const containerBytes = await readZipEntry(required('META-INF/container.xml'), signal);
    if (containerBytes.byteLength > MAX_XML_BYTES) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES);
    }
    const container = parseXml(new TextDecoder().decode(containerBytes), 'PUBLICATION_STRUCTURE_INVALID');
    const rootfile = container.querySelector('rootfile')?.getAttribute('full-path');
    if (!rootfile) throw new Error('PUBLICATION_STRUCTURE_INVALID');
    const opfPath = normalizeEpubArchivePath(rootfile);
    const opfBytes = await readZipEntry(required(opfPath), signal);
    if (opfBytes.byteLength > MAX_XML_BYTES) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES);
    }
    const opf = parseXml(new TextDecoder().decode(opfBytes), 'PUBLICATION_STRUCTURE_INVALID');
    const encryptionEntry = byPath.get('META-INF/encryption.xml');
    if (encryptionEntry) {
      const encryptionBytes = await readZipEntry(encryptionEntry, signal);
      if (encryptionBytes.byteLength > MAX_XML_BYTES) {
        rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES);
      }
      const encryption = parseXml(new TextDecoder().decode(encryptionBytes), 'PUBLICATION_DRM_PROTECTED');
      const allowedFontAlgorithms = new Set<string>(
        READER_SAFETY_PROFILES.reflowable.allowedFontObfuscationAlgorithms
      );
      for (const method of encryption.querySelectorAll('EncryptionMethod')) {
        const algorithm = method.getAttribute('Algorithm') ?? '';
        if (!allowedFontAlgorithms.has(algorithm)) {
          rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_DRM_REJECTED);
        }
      }
    }
    const manifestItems = new Map<string, EpubManifestItem>();
    for (const item of opf.querySelectorAll('manifest > item')) {
      const id = item.getAttribute('id');
      const href = item.getAttribute('href');
      const type = item.getAttribute('media-type')?.trim();
      if (!id || !href || !type) continue;
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
      const navEntry = required(navItem.path);
      if (navEntry.uncompressedSize > MAX_XML_BYTES) {
        rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES);
      }
      const nav = parseXml(new TextDecoder().decode(await readZipEntry(navEntry, signal)), 'PUBLICATION_STRUCTURE_INVALID');
      epub3Toc = parseEpub3Navigation(nav, navItem.path, knownManifestPaths);
    }
    let ncxToc: LocalPublicationTocEntry[] = [];
    if (epub3Toc.length === 0) {
      const spineTocId = opf.querySelector('spine')?.getAttribute('toc');
      const ncxItem = resolveEpub2NcxManifestItem(manifestItems, spineTocId);
      if (ncxItem) {
        const ncxEntry = required(ncxItem.path);
        if (ncxEntry.uncompressedSize > MAX_XML_BYTES) {
          rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES);
        }
        const ncx = parseXml(new TextDecoder().decode(await readZipEntry(ncxEntry, signal)), 'PUBLICATION_STRUCTURE_INVALID');
        ncxToc = parseEpub2NcxNavigation(ncx, ncxItem.path, knownManifestPaths);
      }
    }
    const authoredToc = resolveEpubNavigation(epub3Toc, ncxToc, []);
    const titleByPath = titleByTocPath(authoredToc);
    const itemByPath = new Map([...manifestItems.values()].map((item) => [item.path, item]));
    const rawReads = new Map<string, Promise<Uint8Array>>();
    const resourceReads = new Map<string, Promise<Uint8Array>>();
    const assetUrls = new Map<string, Promise<string | null>>();
    const rawBytes = (path: string): Promise<Uint8Array> => {
      const existing = rawReads.get(path);
      if (existing) return existing;
      const pending = readZipEntry(required(path), signal);
      rawReads.set(path, pending);
      return pending;
    };
    const assetUrl = (path: string, ancestors: ReadonlySet<string> = new Set()): Promise<string | null> => {
      if (ancestors.has(path) || !itemByPath.has(path)) return Promise.resolve(null);
      const existing = assetUrls.get(path);
      if (existing) return existing;
      const pending = (async () => {
        const item = itemByPath.get(path);
        if (!item || /html|xhtml/i.test(item.type)) return null;
        const nextAncestors = new Set(ancestors);
        nextAncestors.add(path);
        let bytes = await rawBytes(path);
        if (item.type === 'text/css') {
          const css = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
          bytes = utf8(await rewriteCssUrls(css, path, assetUrl, nextAncestors));
        } else if (item.type === 'image/svg+xml') {
          const svg = parseXml(new TextDecoder('utf-8', { fatal: true }).decode(bytes), 'PUBLICATION_MARKUP_INVALID');
          sanitizeAuthoredMarkup(svg);
          await rewriteAuthoredDocumentReferences(svg, async (raw) => {
            const resolved = resolveArchivePath(path, raw);
            return resolved ? assetUrl(resolved, nextAncestors) : null;
          });
          bytes = utf8(new XMLSerializer().serializeToString(svg));
        }
        const url = URL.createObjectURL(new Blob([Uint8Array.from(bytes).buffer], { type: item.type }));
        objectUrls.add(url);
        return url;
      })();
      assetUrls.set(path, pending);
      return pending;
    };
    const resourceBytes = (path: string): Promise<Uint8Array> => {
      const existing = resourceReads.get(path);
      if (existing) return existing;
      const pending = (async () => {
        const item = itemByPath.get(path);
        if (!item) throw new Error('PUBLICATION_RESOURCE_NOT_FOUND');
        const bytes = await rawBytes(path);
        if (/html|xhtml/i.test(item.type)) return sanitizeEpubDocument(bytes, path, assetUrl);
        if (item.type === 'text/css') {
          return utf8(await rewriteCssUrls(
            new TextDecoder('utf-8', { fatal: true }).decode(bytes),
            path,
            assetUrl,
            new Set([path])
          ));
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
      if (!item || !/html|xhtml/i.test(item.type)) continue;
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
    const toc = resolveEpubNavigation(epub3Toc, ncxToc, readingOrder);
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
