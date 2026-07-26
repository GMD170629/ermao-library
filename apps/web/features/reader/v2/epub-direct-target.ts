type EpubHrefUnit = { href?: string | null };

function normalizeHref(value: string, includeFragment = true) {
  const trimmed = value.trim();
  const fragmentIndex = trimmed.indexOf('#');
  const path = (fragmentIndex >= 0 ? trimmed.slice(0, fragmentIndex) : trimmed)
    .replace(/^\.?\//, '')
    .replace(/\\/g, '/')
    .toLowerCase();
  return includeFragment && fragmentIndex >= 0 ? `${path}${trimmed.slice(fragmentIndex)}` : path;
}

function sameResourcePath(left: string, right: string) {
  return left === right || left.endsWith(`/${right}`) || right.endsWith(`/${left}`);
}

/** Only bootstrap-owned TOC hrefs may become direct EPUB restore targets. */
export function resolveRequestedEpubHref(units: EpubHrefUnit[], requestedHref: string | null | undefined) {
  if (!requestedHref?.trim()) return null;
  const requestedKey = normalizeHref(requestedHref);
  const exact = units.find((unit) => unit.href && normalizeHref(unit.href) === requestedKey);
  if (exact?.href) return exact.href;
  if (requestedHref.includes('#')) return null;
  const requestedPath = normalizeHref(requestedHref, false);
  const matches = units.filter((unit) => unit.href && sameResourcePath(normalizeHref(unit.href, false), requestedPath));
  return matches.length === 1 ? matches[0].href ?? null : null;
}
