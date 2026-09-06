import type { ReaderNavigationEntry } from '@shuku/reader-core';
import { hrefFragment, samePublicationResource } from './readium-navigation';

/** Engine-supplied fragments can distinguish chapters sharing one resource. */
export function currentReadiumChapter(
  entries: readonly ReaderNavigationEntry[],
  href: string,
  fragments: readonly string[]
): ReaderNavigationEntry | null {
  const candidates = flatten(entries).filter((entry) => entry.href && samePublicationResource(entry.href, href));
  const identifiers = new Set([hrefFragment(href).slice(1), ...fragments].filter(Boolean));
  const exact = candidates.filter((entry) => entry.href && identifiers.has(hrefFragment(entry.href).slice(1)));
  if (exact.length === 1) return exact[0] ?? null;
  return candidates.length === 1 ? candidates[0] ?? null : null;
}

function flatten(entries: readonly ReaderNavigationEntry[]): ReaderNavigationEntry[] {
  return entries.flatMap((entry) => [entry, ...flatten(entry.children ?? [])]);
}
