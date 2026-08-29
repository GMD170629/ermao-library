import { BlobReader, ZipReader, type Entry, type FileEntry } from '@zip.js/zip.js';
import type { ReflowableFormat } from '@shuku/reader-core';
import { openMobiPublication } from '../original-publication/mobi-publication';
import {
  createLocalPublication,
  type ReadiumPublication
} from '../original-publication/local-publication';
import { openTextPublication } from '../original-publication/text-publication';

const MAX_ARCHIVE_ENTRIES = 100_000;
const MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024;
const MAX_ENTRY_BYTES = 256 * 1024 * 1024;
const MAX_XML_BYTES = 16 * 1024 * 1024;
const MAX_COMPRESSION_RATIO = 200;
function bareHref(href: string): string {
  return href.split('#', 1)[0]?.split('?', 1)[0] ?? href;
}

function utf8(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function parseXml(value: string, code: string): XMLDocument {
  if (/<!DOCTYPE|<!ENTITY/i.test(value)) throw new Error('PUBLICATION_SECURITY_REJECTED');
  const document = new DOMParser().parseFromString(value, 'application/xml');
  if (document.querySelector('parsererror')) throw new Error(code);
  return document;
}

function publicationTextLength(bytes: Uint8Array): number {
  const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const document = parseXml(source, 'PUBLICATION_MARKUP_INVALID');
  return Math.max(1, (document.body?.textContent ?? document.documentElement.textContent ?? '').length);
}

function normalizeArchivePath(value: string): string {
  if (!value || value.includes('\\') || value.includes('\0') || value.startsWith('/') || /^[a-z]:/i.test(value)) {
    throw new Error('PUBLICATION_SECURITY_REJECTED');
  }
  const segments = value.split('/');
  if (segments.some((segment) => segment === '' || segment === '.' || segment === '..')) {
    throw new Error('PUBLICATION_SECURITY_REJECTED');
  }
  return segments.join('/');
}

function resolveArchivePath(base: string, relative: string): string | null {
  const trimmed = relative.trim();
  if (!trimmed || trimmed.startsWith('#')) return null;
  if (/^(?:javascript|file|data|blob):/i.test(trimmed)) throw new Error('PUBLICATION_SECURITY_REJECTED');
  if (/^https?:/i.test(trimmed) || trimmed.startsWith('//')) return null;
  if (/^[a-z][a-z0-9+.-]*:/i.test(trimmed)) throw new Error('PUBLICATION_SECURITY_REJECTED');
  const path = bareHref(trimmed);
  const baseSegments = base.split('/').slice(0, -1);
  for (const segment of path.split('/')) {
    if (!segment || segment === '.') continue;
    if (segment === '..') {
      if (baseSegments.length === 0) throw new Error('PUBLICATION_SECURITY_REJECTED');
      baseSegments.pop();
    } else {
      baseSegments.push(segment);
    }
  }
  return normalizeArchivePath(baseSegments.join('/'));
}

function mimeFromPath(path: string): string {
  const extension = path.toLowerCase().split('.').pop();
  return ({
    xhtml: 'application/xhtml+xml', html: 'text/html', htm: 'text/html', css: 'text/css',
    jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif', webp: 'image/webp',
    svg: 'image/svg+xml', otf: 'font/otf', ttf: 'font/ttf', woff: 'font/woff', woff2: 'font/woff2',
    ncx: 'application/x-dtbncx+xml', xml: 'application/xml'
  } as Readonly<Record<string, string>>)[extension ?? ''] ?? 'application/octet-stream';
}

function fileEntry(entry: Entry): entry is FileEntry {
  return entry.directory === false;
}

async function readZipEntry(entry: FileEntry, signal?: AbortSignal): Promise<Uint8Array> {
  const buffer = await entry.arrayBuffer({ signal, strictness: 'strict', checkLocalDirectory: true, checkCrc32: true, checkOverlappingEntry: true });
  return new Uint8Array(buffer);
}

async function rewriteCssUrls(
  source: string,
  href: string,
  assetUrl: (path: string, ancestors?: ReadonlySet<string>) => Promise<string | null>,
  ancestors: ReadonlySet<string>
): Promise<string> {
  if (/@import\b|expression\s*\(|-moz-binding|behavior\s*:/i.test(source)) {
    throw new Error('PUBLICATION_SECURITY_REJECTED');
  }
  const expression = /url\(\s*(['"]?)([^)'"\s]+)\1\s*\)/gi;
  let rewritten = '';
  let offset = 0;
  for (const match of source.matchAll(expression)) {
    const index = match.index;
    if (index === undefined) continue;
    rewritten += source.slice(offset, index);
    const raw = match[2] ?? '';
    const resolved = resolveArchivePath(href, raw);
    const url = resolved ? await assetUrl(resolved, ancestors) : null;
    rewritten += url ? `url("${url}")` : 'url("")';
    offset = index + match[0].length;
  }
  return rewritten + source.slice(offset);
}

async function sanitizeEpubDocument(
  bytes: Uint8Array,
  href: string,
  assetUrl: (path: string) => Promise<string | null>
): Promise<Uint8Array> {
  if (bytes.byteLength > MAX_ENTRY_BYTES) throw new Error('PUBLICATION_PARSER_LIMIT');
  const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const document = parseXml(source, 'PUBLICATION_MARKUP_INVALID');
  for (const element of document.querySelectorAll('script, iframe, object, embed, form, base')) element.remove();
  for (const element of document.querySelectorAll('*')) {
    for (const attribute of [...element.attributes]) if (attribute.name.toLowerCase().startsWith('on')) element.removeAttribute(attribute.name);
  }
  const rewrites: readonly Readonly<{ selector: string; attribute: string }>[] = [
    { selector: 'img[src]', attribute: 'src' }, { selector: 'image[href]', attribute: 'href' },
    { selector: 'link[href]', attribute: 'href' }, { selector: 'source[src]', attribute: 'src' },
    { selector: 'video[poster]', attribute: 'poster' }, { selector: 'audio[src]', attribute: 'src' }
  ];
  for (const rewrite of rewrites) {
    for (const element of document.querySelectorAll(rewrite.selector)) {
      const raw = element.getAttribute(rewrite.attribute) ?? '';
      const resolved = resolveArchivePath(href, raw);
      if (!resolved) {
        element.removeAttribute(rewrite.attribute);
        continue;
      }
      const url = await assetUrl(resolved);
      if (url) element.setAttribute(rewrite.attribute, url); else element.removeAttribute(rewrite.attribute);
    }
  }
  for (const element of document.querySelectorAll('a[href], area[href]')) {
    const raw = element.getAttribute('href')?.trim() ?? '';
    if (/^(?:javascript|file|data|blob):/i.test(raw)) throw new Error('PUBLICATION_SECURITY_REJECTED');
  }
  for (const element of document.querySelectorAll('style')) {
    element.textContent = await rewriteCssUrls(element.textContent ?? '', href, assetUrl, new Set());
  }
  for (const element of document.querySelectorAll('[style]')) {
    element.setAttribute('style', await rewriteCssUrls(element.getAttribute('style') ?? '', href, assetUrl, new Set()));
  }
  return utf8(new XMLSerializer().serializeToString(document));
}

async function openEpub(blob: Blob, fallbackTitle: string, signal?: AbortSignal): Promise<ReadiumPublication> {
  const reader = new ZipReader(new BlobReader(blob), { strictness: 'strict', checkOverlappingEntry: true });
  const objectUrls = new Set<string>();
  try {
    const rawEntries = await reader.getEntries({ strictness: 'strict', filenameValidation: 'strict' });
    const entries = rawEntries.filter(fileEntry);
    if (entries.length === 0 || entries.length > MAX_ARCHIVE_ENTRIES) throw new Error('PUBLICATION_PARSER_LIMIT');
    const byPath = new Map<string, FileEntry>();
    let totalExpanded = 0;
    for (const entry of entries) {
      const path = normalizeArchivePath(entry.filename);
      if (entry.encrypted || entry.symlink || byPath.has(path)) throw new Error('PUBLICATION_SECURITY_REJECTED');
      if (entry.uncompressedSize > MAX_ENTRY_BYTES || (entry.compressedSize > 0 && entry.uncompressedSize / entry.compressedSize > MAX_COMPRESSION_RATIO)) throw new Error('PUBLICATION_PARSER_LIMIT');
      totalExpanded += entry.uncompressedSize;
      if (totalExpanded > MAX_EXPANDED_BYTES) throw new Error('PUBLICATION_PARSER_LIMIT');
      byPath.set(path, entry);
    }
    const required = (path: string) => {
      const entry = byPath.get(path);
      if (!entry) throw new Error('PUBLICATION_STRUCTURE_INVALID');
      return entry;
    };
    const mime = new TextDecoder().decode(await readZipEntry(required('mimetype'), signal)).trim();
    if (mime !== 'application/epub+zip') throw new Error('PUBLICATION_STRUCTURE_INVALID');
    const containerBytes = await readZipEntry(required('META-INF/container.xml'), signal);
    if (containerBytes.byteLength > MAX_XML_BYTES) throw new Error('PUBLICATION_PARSER_LIMIT');
    const container = parseXml(new TextDecoder().decode(containerBytes), 'PUBLICATION_STRUCTURE_INVALID');
    const rootfile = container.querySelector('rootfile')?.getAttribute('full-path');
    if (!rootfile) throw new Error('PUBLICATION_STRUCTURE_INVALID');
    const opfPath = normalizeArchivePath(rootfile);
    const opfBytes = await readZipEntry(required(opfPath), signal);
    if (opfBytes.byteLength > MAX_XML_BYTES) throw new Error('PUBLICATION_PARSER_LIMIT');
    const opf = parseXml(new TextDecoder().decode(opfBytes), 'PUBLICATION_STRUCTURE_INVALID');
    const encryptionEntry = byPath.get('META-INF/encryption.xml');
    if (encryptionEntry) {
      const encryptionBytes = await readZipEntry(encryptionEntry, signal);
      if (encryptionBytes.byteLength > MAX_XML_BYTES) throw new Error('PUBLICATION_PARSER_LIMIT');
      const encryption = parseXml(new TextDecoder().decode(encryptionBytes), 'PUBLICATION_SECURITY_REJECTED');
      const allowedFontAlgorithms = new Set([
        'http://www.idpf.org/2008/embedding',
        'http://ns.adobe.com/pdf/enc#RC'
      ]);
      for (const method of encryption.querySelectorAll('EncryptionMethod')) {
        const algorithm = method.getAttribute('Algorithm') ?? '';
        if (!allowedFontAlgorithms.has(algorithm)) throw new Error('PUBLICATION_DRM_PROTECTED');
      }
    }
    const manifestItems = new Map<string, Readonly<{ path: string; type: string; properties: string }>>();
    for (const item of opf.querySelectorAll('manifest > item')) {
      const id = item.getAttribute('id');
      const href = item.getAttribute('href');
      if (!id || !href) continue;
      const path = resolveArchivePath(opfPath, href);
      if (!path || !byPath.has(path)) throw new Error('PUBLICATION_STRUCTURE_INVALID');
      manifestItems.set(id, {
        path,
        type: item.getAttribute('media-type') || mimeFromPath(path),
        properties: item.getAttribute('properties') ?? ''
      });
    }
    const toc: Array<{ href: string; title: string }> = [];
    const knownManifestPaths = new Set([...manifestItems.values()].map((item) => item.path));
    const navItem = [...manifestItems.values()].find((item) => item.properties.split(/\s+/).includes('nav'));
    if (navItem) {
      const navEntry = required(navItem.path);
      if (navEntry.uncompressedSize > MAX_XML_BYTES) throw new Error('PUBLICATION_PARSER_LIMIT');
      const nav = parseXml(new TextDecoder().decode(await readZipEntry(navEntry, signal)), 'PUBLICATION_STRUCTURE_INVALID');
      for (const anchor of nav.querySelectorAll('nav a[href]')) {
        const rawHref = anchor.getAttribute('href') ?? '';
        const path = resolveArchivePath(navItem.path, rawHref);
        const label = anchor.textContent?.replace(/\s+/g, ' ').trim();
        if (!path || !label || !knownManifestPaths.has(path)) continue;
        const fragment = rawHref.includes('#') ? `#${rawHref.split('#').slice(1).join('#')}` : '';
        toc.push({ href: `${path}${fragment}`, title: label });
      }
    }
    const titleByPath = new Map(toc.map((entry) => [bareHref(entry.href), entry.title]));
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
          for (const element of svg.querySelectorAll('script, foreignObject, iframe, object, embed')) element.remove();
          for (const element of svg.querySelectorAll('*')) {
            for (const attribute of [...element.attributes]) {
              if (attribute.name.toLowerCase().startsWith('on')) element.removeAttribute(attribute.name);
              if (attribute.localName === 'href') {
                const raw = attribute.value.trim();
                if (!raw || raw.startsWith('#')) continue;
                if (/^(?:https?|javascript|file|data|blob):/i.test(raw) || raw.startsWith('//')) {
                  throw new Error('PUBLICATION_SECURITY_REJECTED');
                }
                const resolved = resolveArchivePath(path, raw);
                const replacement = resolved ? await assetUrl(resolved, nextAncestors) : null;
                if (replacement) element.setAttributeNS(attribute.namespaceURI, attribute.name, replacement);
                else element.removeAttributeNS(attribute.namespaceURI, attribute.localName);
              }
            }
          }
          for (const element of svg.querySelectorAll('style')) {
            element.textContent = await rewriteCssUrls(element.textContent ?? '', path, assetUrl, nextAncestors);
          }
          for (const element of svg.querySelectorAll('[style]')) {
            element.setAttribute('style', await rewriteCssUrls(element.getAttribute('style') ?? '', path, assetUrl, nextAncestors));
          }
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
      const positionLength = publicationTextLength(await readZipEntry(entry, signal));
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
    return createLocalPublication({
      title,
      language,
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
export async function openReadiumPublication(blob: Blob, format: ReflowableFormat, title: string, signal?: AbortSignal): Promise<ReadiumPublication> {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  if (format === 'epub') return openEpub(blob, title, signal);
  if (format === 'txt' || format === 'fb2') return openTextPublication(blob, format, title, signal);
  return openMobiPublication(blob, format, title, signal);
}
