export function requestedPdfPage(value: string | null, pageCount: number | null): number | null {
  if (!value) return null;
  const pageNumber = Number(value);
  if (!Number.isInteger(pageNumber) || pageNumber < 1) return null;
  if (pageCount !== null && pageNumber > pageCount) return null;
  return pageNumber;
}

