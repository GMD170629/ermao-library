type PublicationHrefUnit = { href?: string | null };

function normalizeHref(value: string, includeFragment = true) {
  const trimmed = value.trim();
  const fragmentIndex = trimmed.indexOf('#');
  const path = (fragmentIndex >= 0 ? trimmed.slice(0, fragmentIndex) : trimmed)
    .replace(/^\.\//, '')
    .replace(/\\/g, '/')
    .toLowerCase();
  return includeFragment && fragmentIndex >= 0 ? `${path}${trimmed.slice(fragmentIndex)}` : path;
}

/** Only bootstrap-owned Publication TOC hrefs may become direct reader targets. */
export function resolveRequestedPublicationHref(
  units: PublicationHrefUnit[],
  requestedHref: string | null | undefined
) {
  if (!requestedHref?.trim()) return null;
  const requestedKey = normalizeHref(requestedHref);
  const exact = units.find((unit) => unit.href && normalizeHref(unit.href) === requestedKey);
  if (exact?.href) return exact.href;
  if (requestedHref.includes('#')) return null;
  return units.find((unit) => (
    unit.href && normalizeHref(unit.href, false) === normalizeHref(requestedHref, false)
  ))?.href ?? null;
}
