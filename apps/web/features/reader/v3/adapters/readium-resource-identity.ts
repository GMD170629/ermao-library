function normalizedPath(value: string) {
  try {
    return new URL(value, 'https://reader.invalid/').pathname
      .replace(/\/{2,}/gu, '/')
      .replace(/^\/+|\/+$/gu, '');
  } catch {
    return '';
  }
}

function pathSuffixMatches(candidatePath: string, resourcePath: string) {
  return candidatePath === resourcePath || candidatePath.endsWith(`/${resourcePath}`);
}

/**
 * Maps a Readium frame URL (normally a blob URL plus an injected base URL)
 * back to the publication-owned resource href used by Reader locations.
 */
export function resolveReadiumDocumentResourceHref(
  documentUrls: readonly string[],
  resourceHrefs: readonly string[],
  fallbackHref: string
) {
  const resources = resourceHrefs
    .map((href) => ({ href, path: normalizedPath(href) }))
    .filter((resource) => resource.path.length > 0)
    .sort((left, right) => right.path.length - left.path.length);

  for (const documentUrl of documentUrls) {
    const candidatePath = normalizedPath(documentUrl);
    if (!candidatePath) continue;
    const match = resources.find((resource) => pathSuffixMatches(candidatePath, resource.path));
    if (match) return match.href.split('#', 1)[0] ?? match.href;
  }
  return fallbackHref;
}
