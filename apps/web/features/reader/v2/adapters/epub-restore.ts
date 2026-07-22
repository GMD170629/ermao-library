import type { EpubLocation } from '@shuku/reader-core';

export type EpubRestoreTarget =
  | { kind: 'cfi'; value: string }
  | { kind: 'href'; value: string }
  | { kind: 'spine'; value: number }
  | { kind: 'progression'; value: number }
  | { kind: 'start' };

export function epubRestoreTargets(location: EpubLocation | null | undefined): EpubRestoreTarget[] {
  const targets: EpubRestoreTarget[] = [];
  if (location?.cfi?.trim()) targets.push({ kind: 'cfi', value: location.cfi.trim() });
  if (location?.href?.trim()) targets.push({ kind: 'href', value: location.href.trim() });
  if (typeof location?.spineIndex === 'number' && Number.isFinite(location.spineIndex)) {
    targets.push({ kind: 'spine', value: Math.max(0, Math.round(location.spineIndex)) });
  }
  if (typeof location?.progression === 'number' && Number.isFinite(location.progression)) {
    targets.push({ kind: 'progression', value: Math.max(0, Math.min(1, location.progression)) });
  }
  targets.push({ kind: 'start' });
  return targets;
}

export async function restoreEpubLocation(location: EpubLocation | null | undefined, display: (target: EpubRestoreTarget) => Promise<void>) {
  let lastError: unknown;
  for (const target of epubRestoreTargets(location)) {
    try {
      await display(target);
      return target;
    } catch (reason) {
      lastError = reason;
    }
  }
  throw lastError instanceof Error ? lastError : new Error('EPUB restore failed');
}

export function classifyEpubHref(value: string): { kind: 'internal' | 'external' | 'blocked'; href: string } {
  const href = value.trim();
  if (!href) return { kind: 'blocked', href };
  if (href.startsWith('//')) return { kind: 'external', href: `https:${href}` };
  const scheme = href.match(/^([a-z][a-z0-9+.-]*):/i)?.[1]?.toLowerCase();
  if (!scheme || scheme === 'epubcfi') return { kind: 'internal', href };
  if (scheme === 'http' || scheme === 'https' || scheme === 'mailto' || scheme === 'tel') {
    return { kind: 'external', href };
  }
  return { kind: 'blocked', href };
}

export function resolveEpubDocumentHref(target: string, currentHref?: string) {
  const trimmed = target.trim();
  if (!trimmed || /^(?:https?:|mailto:|tel:|epubcfi\()/i.test(trimmed)) return trimmed;
  if (!currentHref) return trimmed.replace(/^\.\//, '');
  try {
    const base = new URL(currentHref.split('#')[0], 'https://shuku-reader.invalid/');
    const resolved = new URL(trimmed, base);
    return `${resolved.pathname.replace(/^\//, '')}${resolved.search}${resolved.hash}`;
  } catch {
    return trimmed;
  }
}

export type EpubTocCfiCandidate = { href: string; cfi: string };

export type EpubViewportResource = {
  href: string;
  left: number;
  top: number;
  right: number;
  bottom: number;
};

function normalizedResourceHref(href: string) {
  const resource = href.trim().split('#')[0]?.split('?')[0] ?? '';
  try {
    return decodeURIComponent(resource).replace(/^\.\//, '');
  } catch {
    return resource.replace(/^\.\//, '');
  }
}

/**
 * epub.js' continuous manager keeps rendered neighbors around the viewport.
 * Choose the resource that actually occupies the reader viewport instead of
 * trusting a transient relocated range that can still point at that neighbor.
 */
export function selectEpubVisibleResource(
  candidates: readonly EpubViewportResource[],
  viewport: Omit<EpubViewportResource, 'href'>,
  preferredHref?: string
) {
  let selected: EpubViewportResource | null = null;
  let selectedArea = 0;
  const preferred = preferredHref ? normalizedResourceHref(preferredHref) : '';
  for (const candidate of candidates) {
    const width = Math.max(0, Math.min(candidate.right, viewport.right) - Math.max(candidate.left, viewport.left));
    const height = Math.max(0, Math.min(candidate.bottom, viewport.bottom) - Math.max(candidate.top, viewport.top));
    const area = width * height;
    if (area <= 0) continue;
    const candidatePreferred = Boolean(preferred && normalizedResourceHref(candidate.href) === preferred);
    const selectedPreferred = Boolean(preferred && selected && normalizedResourceHref(selected.href) === preferred);
    if (area > selectedArea || (area === selectedArea && candidatePreferred && !selectedPreferred)) {
      selected = candidate;
      selectedArea = area;
    }
  }
  return selected?.href ?? null;
}

/**
 * A spine resource can contain many TOC anchors. Select the last anchor that
 * is structurally at or before the relocated CFI instead of treating the
 * resource's first TOC item as the current chapter.
 */
export function selectEpubTocHref(
  resourceHref: string | undefined,
  currentCfi: string | undefined,
  candidates: EpubTocCfiCandidate[],
  compareCfi: (first: string, second: string) => number
) {
  if (!resourceHref || !currentCfi) return resourceHref;
  const resource = normalizedResourceHref(resourceHref);
  let selected: EpubTocCfiCandidate | null = null;
  for (const candidate of candidates) {
    if (!candidate.href.includes('#') || normalizedResourceHref(candidate.href) !== resource) continue;
    try {
      if (compareCfi(candidate.cfi, currentCfi) > 0) continue;
      if (!selected || compareCfi(selected.cfi, candidate.cfi) < 0) selected = candidate;
    } catch {
      // A malformed navigation anchor must not poison relocated events.
    }
  }
  return selected?.href ?? resourceHref;
}

export function approximateEpubProgression(
  index: number | undefined,
  sectionProgression: number | undefined,
  spineLength: number,
  displayedPage?: number,
  displayedTotal?: number
) {
  const displayed = Number.isFinite(displayedPage) && Number.isFinite(displayedTotal) && displayedTotal! > 0
    ? (Math.max(1, displayedPage!) - 1) / displayedTotal!
    : 0;
  const section = Math.max(0, Math.min(1, sectionProgression ?? displayed));
  if (!Number.isFinite(index) || !Number.isFinite(spineLength) || spineLength <= 0) return section;
  return Math.max(0, Math.min(1, (Math.max(0, Math.round(index!)) + section) / spineLength));
}

export function completedEpubProgression(progression: number, atEnd: boolean | undefined) {
  return atEnd ? 1 : Math.max(0, Math.min(1, progression));
}
