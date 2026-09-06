import type { ReaderNavigationEntry } from '@shuku/reader-core';

/** Explicit chapter intents are resolved only against the opened local publication. */
export function resolveRequestedChapterHref(
  entries: readonly ReaderNavigationEntry[],
  navigationKey: string | null | undefined
): string | null {
  if (!navigationKey) return null;
  for (const entry of entries) {
    if (entry.navigationKey === navigationKey) return entry.href ?? null;
    const child = resolveRequestedChapterHref(entry.children ?? [], navigationKey);
    if (child) return child;
  }
  return null;
}
