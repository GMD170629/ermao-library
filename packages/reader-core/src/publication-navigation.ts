const PUBLICATION_NAVIGATION_FORMATS = new Set<string>([
  'epub',
  'mobi',
  'azw',
  'azw3',
  'prc',
  'fb2',
  'txt'
]);

const EXPLICIT_SCHEME = /^[a-z][a-z\d+.-]*:/iu;

export function isPublicationNavigationFormat(
  format: string | null | undefined
): boolean {
  return Boolean(format && PUBLICATION_NAVIGATION_FORMATS.has(format.toLowerCase()));
}

/**
 * Accepts only Publication-owned, publication-relative resource hrefs.
 * Legacy import/native-engine locators are schemes, so they are rejected by
 * the same rule as external URLs instead of being maintained per format.
 */
export function publicationNavigationHref(
  format: string | null | undefined,
  href: string | null | undefined
): string | null {
  if (!isPublicationNavigationFormat(format) || !href?.trim()) return null;
  const target = href.trim();
  if (
    target.startsWith('#')
    || target.startsWith('/')
    || target.startsWith('//')
    || target.includes('\\')
    || EXPLICIT_SCHEME.test(target)
  ) return null;

  const resourcePath = target.split(/[?#]/u, 1)[0];
  if (!resourcePath) return null;
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(resourcePath);
  } catch {
    return null;
  }
  if (decodedPath.split('/').some((segment) => segment === '.' || segment === '..')) {
    return null;
  }
  return target;
}
