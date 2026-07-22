export type ComicDirection = 'ltr' | 'rtl';

export function comicVisualSpreadPages(spreadPages: number[], direction: ComicDirection) {
  return direction === 'rtl' ? [...spreadPages].reverse() : spreadPages;
}
