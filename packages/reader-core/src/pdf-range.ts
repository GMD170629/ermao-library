export const PDF_RANGE_CHUNK_BYTES = 256 * 1024;
export const PDF_RANGE_MAX_REQUEST_BYTES = 1024 * 1024;
export const PDF_RANGE_MAX_CONCURRENT_REQUESTS = 2;
export const PDF_RANGE_MEMORY_CACHE_BYTES = 8 * 1024 * 1024;

export type PdfReaderErrorCode =
  | 'PDF_RANGE_UNSUPPORTED'
  | 'PDF_RANGE_INVALID'
  | 'PDF_RESOURCE_CHANGED'
  | 'NETWORK_UNAVAILABLE'
  | 'PDF_CACHE_IO'
  | 'PDF_ENCRYPTED'
  | 'PDF_INVALID'
  | 'PDF_PAGE_LOAD_FAILED'
  | 'PDF_RENDER_FAILED'
  | 'OUT_OF_MEMORY_RISK';

export type PdfByteRange = Readonly<{ begin: number; end: number }>;

/** Returns aligned, end-exclusive requests capped at one MiB. */
export function planPdfByteRanges(begin: number, end: number, length: number): PdfByteRange[] {
  if (!Number.isInteger(begin) || !Number.isInteger(end) || !Number.isInteger(length)
    || begin < 0 || end <= begin || end > length) throw new RangeError('PDF byte range is invalid');
  const alignedBegin = Math.floor(begin / PDF_RANGE_CHUNK_BYTES) * PDF_RANGE_CHUNK_BYTES;
  const alignedEnd = Math.min(length, Math.ceil(end / PDF_RANGE_CHUNK_BYTES) * PDF_RANGE_CHUNK_BYTES);
  const requests: PdfByteRange[] = [];
  for (let cursor = alignedBegin; cursor < alignedEnd; cursor += PDF_RANGE_MAX_REQUEST_BYTES) {
    requests.push({ begin: cursor, end: Math.min(alignedEnd, cursor + PDF_RANGE_MAX_REQUEST_BYTES) });
  }
  return requests;
}
