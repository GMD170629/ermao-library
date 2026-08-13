import { Locator, LocatorLocations, LocatorText } from '@readium/shared';
import { parseReadiumLocatorEnvelope, type PublicationFingerprint, type ReadiumLocatorEnvelope } from '@shuku/reader-core';
import { resolveReadiumDocumentResourceHref } from './readium-resource-identity';

const BLOCK_SELECTOR = 'h1,h2,h3,h4,h5,h6,p,li,pre,blockquote,figcaption,td,th';

function bounded(value: string | undefined, maximum: number) {
  const normalized = value?.trim();
  return normalized ? Array.from(normalized).slice(0, maximum).join('') : undefined;
}

function selectorFor(element: Element) {
  if (element.id) return `#${CSS.escape(element.id)}`;
  const parts: string[] = [];
  let current: Element | null = element;
  while (current && current.tagName.toLowerCase() !== 'body') {
    const parent: Element | null = current.parentElement;
    if (!parent) break;
    const siblings = Array.from(parent.children).filter((sibling) => sibling.tagName === current?.tagName);
    const suffix = siblings.length > 1 ? `:nth-of-type(${siblings.indexOf(current) + 1})` : '';
    parts.unshift(`${current.tagName.toLowerCase()}${suffix}`);
    current = parent;
  }
  return `body > ${parts.join(' > ')}`;
}

function documentResourceCandidates(document: Document) {
  const baseHref = document.querySelector<HTMLBaseElement>('base[data-readium="true"], base[href]')?.href;
  return [document.location.href, ...(baseHref ? [baseHref] : [])];
}

function frameMatchesHref(frame: HTMLIFrameElement, href: string) {
  try {
    const document = frame.contentDocument;
    if (!document) return false;
    const resourceHref = href.split('#', 1)[0] ?? href;
    return resolveReadiumDocumentResourceHref(documentResourceCandidates(document), [resourceHref], '') === resourceHref;
  } catch {
    return false;
  }
}

function isVisibleFrame(frame: HTMLIFrameElement, container: HTMLElement) {
  const frameRect = frame.getBoundingClientRect();
  const containerRect = container.getBoundingClientRect();
  const style = frame.ownerDocument.defaultView?.getComputedStyle(frame);
  return frameRect.width > 0 && frameRect.height > 0
    && style?.display !== 'none' && style?.visibility !== 'hidden'
    && frameRect.bottom > containerRect.top && frameRect.right > containerRect.left
    && frameRect.top < containerRect.bottom && frameRect.left < containerRect.right;
}

function visibleFramesForHref(container: HTMLElement, href: string) {
  const visibleFrames = Array.from(container.querySelectorAll('iframe'))
    .filter((frame) => isVisibleFrame(frame, container));
  const matchingFrames = visibleFrames.filter((frame) => frameMatchesHref(frame, href));
  return matchingFrames.length > 0 ? matchingFrames : visibleFrames;
}

function blockIsVisible(element: HTMLElement, frame: HTMLIFrameElement) {
  const rect = element.getBoundingClientRect();
  return Boolean(element.textContent?.trim()) && rect.bottom > 0 && rect.right > 0
    && rect.top < frame.clientHeight && rect.left < frame.clientWidth;
}

function firstVisibleBlock(container: HTMLElement, href: string) {
  for (const frame of visibleFramesForHref(container, href)) {
    let document: Document | null = null;
    try { document = frame.contentDocument; } catch { continue; }
    if (!document) continue;
    const elements = Array.from(document.querySelectorAll<HTMLElement>(BLOCK_SELECTOR))
      .filter((element) => blockIsVisible(element, frame))
      .sort((left, right) => {
        const a = left.getBoundingClientRect(); const b = right.getBoundingClientRect();
        return Math.max(0, a.left) - Math.max(0, b.left) || Math.max(0, a.top) - Math.max(0, b.top);
      });
    if (elements[0]) return elements[0];
  }
  return null;
}

function normalizedText(value: string) { return value.normalize('NFC').replace(/\s+/gu, ' ').trim(); }

function visibleTargetBlock(container: HTMLElement, target: ReadiumLocatorEnvelope) {
  const selector = typeof target.payload.locations.cssSelector === 'string'
    ? target.payload.locations.cssSelector
    : null;
  const highlight = normalizedText(target.payload.text?.highlight ?? '');
  for (const frame of visibleFramesForHref(container, target.payload.href)) {
    let document: Document | null = null;
    try { document = frame.contentDocument; } catch { continue; }
    if (!document) continue;
    if (selector) {
      try {
        const selected = document.querySelector<HTMLElement>(selector);
        if (selected && blockIsVisible(selected, frame)) return selected;
      } catch {
        // A portable locator may contain a selector unsupported by this DOM.
        // Text verification below remains a safe independent fallback.
      }
    }
    if (!highlight) continue;
    const matching = Array.from(document.querySelectorAll<HTMLElement>(BLOCK_SELECTOR))
      .find((element) => blockIsVisible(element, frame)
        && normalizedText(bounded(element.textContent ?? undefined, 512) ?? '') === highlight);
    if (matching) return matching;
  }
  return null;
}

function locatorForBlock(
  current: Locator,
  element: HTMLElement,
  publication: PublicationFingerprint,
  resourceHrefs: readonly string[]
) {
  const highlight = bounded(element.textContent ?? undefined, 512);
  if (!highlight) return null;
  const href = resolveReadiumDocumentResourceHref(
    documentResourceCandidates(element.ownerDocument),
    resourceHrefs,
    current.href
  );
  const locator = new Locator({
    href,
    type: current.type,
    title: current.title,
    locations: new LocatorLocations({
      progression: current.locations.progression,
      totalProgression: current.locations.totalProgression,
      position: current.locations.position,
      otherLocations: new Map([['cssSelector', selectorFor(element)]])
    }),
    text: new LocatorText({ highlight })
  });
  return parseReadiumLocatorEnvelope({
    engine: 'readium', platform: 'web', version: 'readium-ts:2.8.2', publication,
    payload: locator.serialize()
  });
}

export function isReadiumTextAnchorUnique(container: HTMLElement, highlight: string) {
  const needle = normalizedText(highlight);
  if (!needle) return false;
  let matches = 0;
  for (const frame of container.querySelectorAll('iframe')) {
    let bodyText = '';
    try { bodyText = normalizedText(frame.contentDocument?.body.textContent ?? ''); } catch { continue; }
    let offset = 0;
    while ((offset = bodyText.indexOf(needle, offset)) >= 0) {
      matches += 1;
      if (matches > 1) return false;
      offset += needle.length;
    }
  }
  return matches === 1;
}

/** Version-locked DOM bridge used because Readium TS 2.8.2 has no public first-visible-block convenience. */
export function captureExactReadiumLocator(
  current: Locator,
  container: HTMLElement,
  publication: PublicationFingerprint,
  resourceHrefs: readonly string[]
): ReadiumLocatorEnvelope | null {
  const element = firstVisibleBlock(container, current.href);
  if (!element) return null;
  return locatorForBlock(current, element, publication, resourceHrefs);
}

/** Re-captures the requested exact block wherever it lands on the visible page. */
export function captureVisibleReadiumTarget(
  target: ReadiumLocatorEnvelope,
  current: Locator,
  container: HTMLElement,
  publication: PublicationFingerprint,
  resourceHrefs: readonly string[]
): ReadiumLocatorEnvelope | null {
  const element = visibleTargetBlock(container, target);
  return element ? locatorForBlock(current, element, publication, resourceHrefs) : null;
}
