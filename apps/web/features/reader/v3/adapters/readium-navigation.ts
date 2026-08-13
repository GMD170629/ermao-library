import type { Publication } from '@readium/shared';
import type { ReaderNavigationEntry } from '@shuku/reader-core';

export function bareHref(href: string) {
  return href.split('#', 1)[0] ?? href;
}

export function hrefFragment(href: string) {
  const hash = href.indexOf('#');
  return hash >= 0 ? href.slice(hash) : '';
}

export function hasExplicitScheme(href: string) {
  return /^[a-z][a-z\d+.-]*:/iu.test(href) || href.startsWith('//');
}

export function isAllowedReadiumExternalHref(href: string) {
  try {
    return ['http:', 'https:', 'mailto:', 'tel:'].includes(new URL(href, 'https://readium.invalid/').protocol)
      && /^[a-z][a-z\d+.-]*:/iu.test(href);
  } catch {
    return false;
  }
}

/** Resolves a publication-relative href without turning relative RWPM links into network URLs. */
export function resolveReadiumHref(href: string, currentHref: string) {
  const candidate = href.trim();
  if (!candidate || hasExplicitScheme(candidate)) return candidate;
  const currentIsAbsolute = hasExplicitScheme(currentHref);
  const currentHasLeadingSlash = currentHref.startsWith('/');
  const base = new URL(currentHref, 'https://readium.invalid/');
  const resolved = new URL(candidate, base);
  if (currentIsAbsolute) return resolved.href;
  const pathname = currentHasLeadingSlash ? resolved.pathname : resolved.pathname.replace(/^\/+/, '');
  return `${pathname}${resolved.search}${resolved.hash}`;
}

export function samePublicationResource(first: string, second: string) {
  if (bareHref(first) === bareHref(second)) return true;
  try {
    const left = new URL(bareHref(first), 'https://readium.invalid/');
    const right = new URL(bareHref(second), 'https://readium.invalid/');
    return left.pathname === right.pathname && left.search === right.search;
  } catch {
    return false;
  }
}

export function findReadiumPublicationResource<T extends { href: string }>(
  items: readonly T[],
  candidates: readonly string[]
) {
  return items.find((item) => candidates.some((candidate) => samePublicationResource(item.href, candidate))) ?? null;
}

function readingOrderIndex(publication: Publication, href: string) {
  return publication.readingOrder.items.findIndex((item) => samePublicationResource(item.href, href));
}

/** Converts the Readium TOC to the Reader-owned, zero-based navigation contract. */
export function readiumNavigationEntries(publication: Publication): ReaderNavigationEntry[] {
  const map = (links: Publication['toc'], path: number[], level: number): ReaderNavigationEntry[] => {
    if (!links) return [];
    return links.items.flatMap((link, offset) => {
      const nextPath = [...path, offset];
      const children = map(link.children, nextPath, level + 1);
      const label = link.title?.trim();
      if (!label) return children;
      const index = readingOrderIndex(publication, link.href);
      const navigationKey = `readium-toc:${nextPath.join('.')}:${link.href}`;
      return [{
        id: navigationKey,
        navigationKey,
        label,
        href: link.href,
        ...(index >= 0 ? { index } : {}),
        level,
        ...(children.length > 0 ? { children } : {})
      }];
    });
  };
  return map(publication.toc, [], 0);
}

export function closestReadiumPosition<T extends { locations: { totalProgression?: number } }>(positions: T[], progression: number): T | null {
  if (positions.length === 0 || !Number.isFinite(progression)) return null;
  const target = Math.max(0, Math.min(1, progression));
  let closest = positions[Math.round(target * (positions.length - 1))] ?? positions[0];
  let distance = Number.POSITIVE_INFINITY;
  for (const position of positions) {
    const total = position.locations.totalProgression;
    if (typeof total !== 'number') continue;
    const candidateDistance = Math.abs(total - target);
    if (candidateDistance < distance) {
      distance = candidateDistance;
      closest = position;
    }
  }
  return closest ?? null;
}

type ReadiumProgressPoint = Readonly<{
  href: string;
  locations: Readonly<{
    progression?: number;
    totalProgression?: number;
  }>;
}>;

function unitProgression(value: number | undefined, fallback = 0) {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(0, Math.min(1, value))
    : fallback;
}

/**
 * Readium's current locator can keep the resource's opening totalProgression
 * for every generated page. Interpolate against the declared publication
 * positions so live pagination still advances through that resource.
 */
export function readiumTotalProgression(
  current: ReadiumProgressPoint,
  positions: readonly ReadiumProgressPoint[]
) {
  const resourceProgression = unitProgression(current.locations.progression);
  const matchingIndexes = positions.flatMap((position, index) => (
    samePublicationResource(position.href, current.href) ? [index] : []
  ));
  if (matchingIndexes.length === 0) {
    return unitProgression(current.locations.totalProgression);
  }

  const resourcePoints = matchingIndexes
    .map((index) => positions[index])
    .filter((position): position is ReadiumProgressPoint => Boolean(position))
    .map((position) => ({
      resource: unitProgression(position.locations.progression),
      total: unitProgression(position.locations.totalProgression)
    }))
    .sort((left, right) => left.resource - right.resource);
  const lower = [...resourcePoints]
    .reverse()
    .find((point) => point.resource <= resourceProgression)
    ?? resourcePoints[0];
  if (!lower) return unitProgression(current.locations.totalProgression);

  const nativeTotal = current.locations.totalProgression;
  if (
    typeof nativeTotal === 'number'
    && Number.isFinite(nativeTotal)
    && Math.abs(nativeTotal - lower.total) > Number.EPSILON
  ) return unitProgression(nativeTotal);

  const upperInResource = resourcePoints.find((point) => point.resource > resourceProgression);
  const finalMatchingIndex = matchingIndexes.at(-1) ?? -1;
  const nextResource = positions.slice(finalMatchingIndex + 1)
    .find((position) => typeof position.locations.totalProgression === 'number');
  const upper = upperInResource ?? {
    resource: 1,
    total: unitProgression(nextResource?.locations.totalProgression, 1)
  };
  if (upper.resource <= lower.resource) return lower.total;
  const ratio = (resourceProgression - lower.resource) / (upper.resource - lower.resource);
  return unitProgression(lower.total + (upper.total - lower.total) * ratio);
}
