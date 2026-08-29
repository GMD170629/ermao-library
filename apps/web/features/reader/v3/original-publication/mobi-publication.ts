import type { ReflowableFormat } from '@shuku/reader-core';
import { createLocalPublication, type ReadiumPublication } from './local-publication';
import { MobiWorkerClient } from './mobi-worker-client';

const MOBI_FORMATS: readonly ReflowableFormat[] = ['mobi', 'azw', 'azw3', 'prc'];

function safeInternalHref(index: number): string {
  return `mobi/resource-${index}.xhtml`;
}

async function sanitizeMarkup(
  bytes: Uint8Array,
  title: string,
  resolveAssetUrl: (sourceName: string) => Promise<string | null>
): Promise<Uint8Array> {
  const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  if (/<!ENTITY/i.test(source)) throw new Error('PUBLICATION_SECURITY_REJECTED');
  // MOBI6 and PalmDOC commonly contain valid HTML which is not XHTML.
  // Parse with the HTML algorithm, then serialize the sanitized DOM as the
  // XHTML bytes expected by the local Readium Publication.
  const document = new DOMParser().parseFromString(source, 'text/html');
  if (!document.documentElement || !document.body || !(document.body.textContent ?? '').trim()) {
    throw new Error('PUBLICATION_MARKUP_INVALID');
  }
  for (const legacy of [...document.querySelectorAll('*')].filter((element) => element.localName.includes(':'))) {
    const replacement = document.createElement('span');
    for (const attribute of [...legacy.attributes]) {
      if (!attribute.name.includes(':') && attribute.name.toLowerCase() !== 'xmlns') {
        replacement.setAttribute(attribute.name, attribute.value);
      }
    }
    replacement.append(...legacy.childNodes);
    legacy.replaceWith(replacement);
  }
  for (const element of document.querySelectorAll('script, iframe, object, embed, form, base')) element.remove();
  for (const element of document.querySelectorAll('*')) {
    for (const attribute of [...element.attributes]) {
      if (attribute.name.toLowerCase().startsWith('on')) element.removeAttribute(attribute.name);
    }
  }
  for (const element of document.querySelectorAll('[src], image[href], link[href]')) {
    const attribute = element.hasAttribute('src') ? 'src' : 'href';
    const value = element.getAttribute(attribute)?.trim() ?? '';
    if (/^(?:javascript|file|data|blob):/i.test(value)) throw new Error('PUBLICATION_SECURITY_REJECTED');
    if (/^https?:/i.test(value) || value.startsWith('//')) {
      element.removeAttribute(attribute);
      continue;
    }
    if (/^[a-z][a-z0-9+.-]*:/i.test(value)) throw new Error('PUBLICATION_SECURITY_REJECTED');
    const raw = value.split('#', 1)[0] ?? '';
    const key = raw.replace(/^\.\//, '');
    const replacement = await resolveAssetUrl(key);
    if (replacement) element.setAttribute(attribute, replacement); else element.removeAttribute(attribute);
  }
  for (const element of document.querySelectorAll('a[href], area[href]')) {
    const href = element.getAttribute('href')?.trim() ?? '';
    if (/^(?:javascript|file|data|blob):/i.test(href)) throw new Error('PUBLICATION_SECURITY_REJECTED');
    if (/^[a-z][a-z0-9+.-]*:/i.test(href) && !/^https?:/i.test(href)) {
      throw new Error('PUBLICATION_SECURITY_REJECTED');
    }
  }
  for (const element of document.querySelectorAll('style')) {
    element.textContent = await rewriteCssUrls(element.textContent ?? '', resolveAssetUrl, new Set());
  }
  for (const element of document.querySelectorAll('[style]')) {
    element.setAttribute('style', await rewriteCssUrls(element.getAttribute('style') ?? '', resolveAssetUrl, new Set()));
  }
  let head = document.querySelector('head');
  if (!head) {
    head = document.createElementNS('http://www.w3.org/1999/xhtml', 'head');
    document.documentElement.prepend(head);
  }
  if (!head.querySelector('title')) {
    const titleElement = document.createElementNS('http://www.w3.org/1999/xhtml', 'title');
    titleElement.textContent = title;
    head.append(titleElement);
  }
  return new TextEncoder().encode(new XMLSerializer().serializeToString(document));
}

async function rewriteCssUrls(
  source: string,
  resolveAssetUrl: (sourceName: string, ancestors?: ReadonlySet<number>) => Promise<string | null>,
  ancestors: ReadonlySet<number>
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
    const replacement = await resolveAssetUrl(match[2] ?? '', ancestors);
    rewritten += replacement ? `url("${replacement}")` : 'url("")';
    offset = index + match[0].length;
  }
  return rewritten + source.slice(offset);
}

/** Opens MOBI/AZW/AZW3/PRC through the same mobi-core C ABI used by native apps. */
export async function openMobiPublication(
  blob: Blob,
  format: ReflowableFormat,
  fallbackTitle: string,
  signal?: AbortSignal
): Promise<ReadiumPublication> {
  if (!MOBI_FORMATS.includes(format)) throw new Error('MOBI_FORMAT_INVALID');
  const client = new MobiWorkerClient(signal);
  const objectUrls = new Set<string>();
  try {
    const opened = await client.open(blob, `publication.${format}`);
    if (opened.readingOrder.length === 0 || new Set(opened.readingOrder).size !== opened.readingOrder.length) {
      throw new Error('PUBLICATION_STRUCTURE_INVALID');
    }
    const resourceByIndex = new Map(opened.resources.map((resource) => [resource.index, resource]));
    if (resourceByIndex.size !== opened.resources.length) throw new Error('PUBLICATION_STRUCTURE_INVALID');
    for (const resource of opened.resources) {
      if (!resource.sourceName.trim() || !resource.mediaType.trim()) throw new Error('PUBLICATION_STRUCTURE_INVALID');
    }
    const readingOrderSet = new Set(opened.readingOrder);
    if (opened.readingOrder.some((index) => !resourceByIndex.has(index))) {
      throw new Error('MOBI_READING_ORDER_INVALID');
    }
    const resourceByName = new Map<string, number>();
    for (const resource of opened.resources) {
      resourceByName.set(resource.sourceName, resource.index);
      resourceByName.set(resource.sourceName.split('/').pop() ?? resource.sourceName, resource.index);
    }
    const rawReads = new Map<number, Promise<Uint8Array>>();
    const markupReads = new Map<number, Promise<Uint8Array>>();
    const assetUrls = new Map<number, Promise<string | null>>();
    const readResource = (resourceIndex: number): Promise<Uint8Array> => {
      const existing = rawReads.get(resourceIndex);
      if (existing) return existing;
      const resource = resourceByIndex.get(resourceIndex);
      if (!resource) return Promise.reject(new Error('MOBI_RESOURCE_MISSING'));
      const pending = client.read(resourceIndex).then((bytes) => {
        if (bytes.byteLength !== resource.decodedLength) throw new Error('MOBI_RESOURCE_LENGTH_INVALID');
        return new Uint8Array(bytes);
      });
      rawReads.set(resourceIndex, pending);
      return pending;
    };
    const resolveAssetUrl = (sourceName: string, ancestors: ReadonlySet<number> = new Set()): Promise<string | null> => {
      const normalized = sourceName.replace(/^\.\//, '').split('#', 1)[0] ?? '';
      const resourceIndex = resourceByName.get(normalized) ?? resourceByName.get(normalized.split('/').pop() ?? '');
      if (resourceIndex === undefined || readingOrderSet.has(resourceIndex) || ancestors.has(resourceIndex)) {
        return Promise.resolve(null);
      }
      const existing = assetUrls.get(resourceIndex);
      if (existing) return existing;
      const pending = (async () => {
        const resource = resourceByIndex.get(resourceIndex);
        if (!resource) return null;
        let bytes = await readResource(resourceIndex);
        if (resource.mediaType === 'text/css') {
          const nextAncestors = new Set(ancestors);
          nextAncestors.add(resourceIndex);
          bytes = new TextEncoder().encode(await rewriteCssUrls(
            new TextDecoder('utf-8', { fatal: true }).decode(bytes),
            resolveAssetUrl,
            nextAncestors
          ));
        }
        const url = URL.createObjectURL(new Blob([Uint8Array.from(bytes).buffer], { type: resource.mediaType }));
        objectUrls.add(url);
        return url;
      })();
      assetUrls.set(resourceIndex, pending);
      return pending;
    };
    const readingOrder = opened.readingOrder.map((resourceIndex, position) => {
      const resource = resourceByIndex.get(resourceIndex);
      if (!resource) throw new Error('MOBI_READING_ORDER_INVALID');
      const title = opened.toc.find((entry) => entry.resourceIndex === resourceIndex)?.title ?? `Section ${position + 1}`;
      return {
        href: safeInternalHref(resourceIndex),
        type: 'application/xhtml+xml',
        title,
        size: resource.decodedLength,
        positionLength: resource.decodedLength,
        read: () => {
          const existing = markupReads.get(resourceIndex);
          if (existing) return existing;
          const pending = readResource(resourceIndex).then((bytes) => sanitizeMarkup(bytes, title, resolveAssetUrl));
          markupReads.set(resourceIndex, pending);
          return pending;
        }
      };
    });
    const hrefByResource = new Map(opened.readingOrder.map((index) => [index, safeInternalHref(index)]));
    const toc = opened.toc.flatMap((entry) => {
      const href = hrefByResource.get(entry.resourceIndex);
      return href ? [{ href: entry.fragment ? `${href}#${encodeURIComponent(entry.fragment)}` : href, title: entry.title }] : [];
    });
    return createLocalPublication({
      title: opened.title ?? fallbackTitle,
      language: opened.language,
      readingOrder,
      toc,
      extraResources: opened.resources
        .filter((resource) => !readingOrderSet.has(resource.index))
        .map((resource) => ({
          href: `mobi/resource-${resource.index}`,
          type: resource.mediaType,
          size: resource.decodedLength,
          read: () => readResource(resource.index)
        })),
      onClose: () => {
        for (const url of objectUrls) URL.revokeObjectURL(url);
        void client.close().catch(() => client.terminate());
      }
    });
  } catch (cause) {
    client.terminate();
    for (const url of objectUrls) URL.revokeObjectURL(url);
    throw cause;
  }
}
