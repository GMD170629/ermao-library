export type EpubNavigationTarget = {
  href?: string | null;
  index?: number;
  sectionIndex?: number;
};

function navigationSectionIndex(item: EpubNavigationTarget) {
  return typeof item.sectionIndex === 'number' && Number.isFinite(item.sectionIndex)
    ? item.sectionIndex
    : item.index;
}

/**
 * Resolves a spine resource that is not itself present in the TOC to the last
 * navigation entry that started before it. Exact-section resources are left
 * alone so fragment-aware matching can decide between multiple anchors.
 */
export function resolveEpubSpineIntervalHref(
  items: readonly EpubNavigationTarget[],
  currentSectionIndex: unknown,
  fallbackHref: string | undefined
) {
  if (typeof currentSectionIndex !== 'number' || !Number.isFinite(currentSectionIndex)) return fallbackHref;
  const indexed = items
    .map((item, order) => ({ href: item.href, sectionIndex: navigationSectionIndex(item), order }))
    .filter((item): item is { href: string; sectionIndex: number; order: number } => (
      Boolean(item.href)
      && typeof item.sectionIndex === 'number'
      && Number.isFinite(item.sectionIndex)
    ));
  if (indexed.some((item) => item.sectionIndex === currentSectionIndex)) return fallbackHref;
  const previous = indexed
    .filter((item) => item.sectionIndex < currentSectionIndex)
    .sort((left, right) => left.sectionIndex - right.sectionIndex || left.order - right.order)
    .at(-1);
  return previous?.href ?? fallbackHref;
}

function decode(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function normalizedHref(value: string) {
  const [rawPath, ...fragmentParts] = value.trim().replace(/\\/g, '/').split('#');
  const path = decode(rawPath).replace(/^\.?\//, '').toLowerCase();
  const fragment = fragmentParts.length > 0 ? decode(fragmentParts.join('#')) : '';
  return { path, fragment, full: fragment ? `${path}#${fragment}` : path };
}

function sameResourcePath(first: string, second: string) {
  return first === second || first.endsWith(`/${second}`) || second.endsWith(`/${first}`);
}

/**
 * Resolves a real TOC target without assuming one TOC entry per spine item.
 * A resource-only location is deliberately left unresolved when that XHTML
 * contains multiple chapter anchors.
 */
export function resolveActiveEpubNavigationIndex(
  items: readonly EpubNavigationTarget[],
  currentHref: unknown,
  sectionIndex: unknown
) {
  if (typeof currentHref === 'string' && currentHref.trim()) {
    const current = normalizedHref(currentHref);
    const exact = items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => item.href && normalizedHref(item.href).full === current.full);
    if (exact.length === 1) return exact[0].index;

    const sameResource = items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => item.href && sameResourcePath(normalizedHref(item.href).path, current.path));
    if (sameResource.length > 0) {
      if (current.fragment) {
        const resourceOnly = sameResource.filter(({ item }) => item.href && !normalizedHref(item.href).fragment);
        return sameResource.length === 1 && resourceOnly.length === 1 ? resourceOnly[0].index : null;
      }
      return sameResource.length === 1 ? sameResource[0].index : null;
    }

    const intervalHref = resolveEpubSpineIntervalHref(items, sectionIndex, currentHref);
    if (intervalHref && normalizedHref(intervalHref).full !== current.full) {
      return resolveActiveEpubNavigationIndex(items, intervalHref, null);
    }
  }

  if (typeof sectionIndex === 'number' && Number.isFinite(sectionIndex)) {
    const matches = items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => navigationSectionIndex(item) === sectionIndex);
    return matches.length === 1 ? matches[0].index : null;
  }
  return null;
}
