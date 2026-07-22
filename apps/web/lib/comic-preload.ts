export const comicPagedPreloadRadius = 2;
export const maxComicPagedPreloadPages = 2;
export const comicPreloadAfterVisibleDelayMs = 120;

export function comicPreloadPages(
  orderedPages: number[],
  currentPage: number,
  visibleCount: number,
  radius = comicPagedPreloadRadius,
  limit = maxComicPagedPreloadPages
) {
  const currentIndex = orderedPages.indexOf(currentPage);
  if (currentIndex < 0 || limit <= 0 || radius <= 0) return [];

  const visibleEnd = Math.min(orderedPages.length, currentIndex + Math.max(1, visibleCount));
  const forwardPages = orderedPages.slice(visibleEnd, visibleEnd + radius);
  const backwardPages = orderedPages.slice(Math.max(0, currentIndex - radius), currentIndex).reverse();
  const selected: number[] = [];
  const seen = new Set<number>();

  for (const page of [...forwardPages, ...backwardPages]) {
    if (seen.has(page)) continue;
    seen.add(page);
    selected.push(page);
    if (selected.length >= limit) break;
  }

  return selected;
}

export function comicRetainedPages(
  orderedPages: number[],
  currentPage: number,
  visibleCount: number,
  radius = comicPagedPreloadRadius
) {
  const currentIndex = orderedPages.indexOf(currentPage);
  if (currentIndex < 0) return [];

  const visibleEnd = Math.min(orderedPages.length, currentIndex + Math.max(1, visibleCount));
  return orderedPages.slice(Math.max(0, currentIndex - radius), Math.min(orderedPages.length, visibleEnd + radius));
}
