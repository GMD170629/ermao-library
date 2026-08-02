/** Import-time synthetic hrefs — not engine navigation targets. */
const PSEUDO_READING_HREF = /^(mobi-section|txt-chapter|fb2-section):/i;

/**
 * Returns false only for known library import pseudo-hrefs that must not be
 * passed to foliate `goTo`/`resolveHref`. All other hrefs (including foliate
 * native `filepos:` / `kindle:pos:` and EPUB spine paths) pass through unchanged.
 */
export function isEngineResolvableReflowableHref(
  _format: string | null | undefined,
  href: string | null | undefined
): boolean {
  if (!href?.trim()) return false;
  return !PSEUDO_READING_HREF.test(href.trim());
}
