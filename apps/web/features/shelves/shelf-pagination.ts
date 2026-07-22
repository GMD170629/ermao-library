export const SHELF_DETAIL_PAGE_SIZE = 20;

export function shelfPageCount(totalItems: number, pageSize = SHELF_DETAIL_PAGE_SIZE) {
  return Math.max(1, Math.ceil(totalItems / pageSize));
}

export function clampShelfPage(page: number, totalItems: number, pageSize = SHELF_DETAIL_PAGE_SIZE) {
  return Math.min(Math.max(1, page), shelfPageCount(totalItems, pageSize));
}

export function shelfPageItems<T>(items: T[], page: number, pageSize = SHELF_DETAIL_PAGE_SIZE) {
  const safePage = clampShelfPage(page, items.length, pageSize);
  const start = (safePage - 1) * pageSize;
  return items.slice(start, start + pageSize);
}

export function shelfPaginationCandidates(page: number, totalPages: number) {
  return Array.from(new Set([1, page - 1, page, page + 1, totalPages]))
    .filter((item) => item >= 1 && item <= totalPages)
    .sort((a, b) => a - b);
}
