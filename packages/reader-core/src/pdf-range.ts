import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_RULES,
  READER_SAFETY_RULE_IDS
} from './reader-safety-policy.generated';

export const PDF_RANGE_CHUNK_BYTES = READER_SAFETY_BUDGETS.pdfRangeChunkBytes;
export const PDF_RANGE_MAX_REQUEST_BYTES = READER_SAFETY_BUDGETS.pdfRangeRequestMaxBytes;
export const PDF_RANGE_MAX_CONCURRENT_REQUESTS = READER_SAFETY_BUDGETS.pdfRangeMaxConcurrent;
export const PDF_RANGE_MEMORY_CACHE_BYTES = READER_SAFETY_BUDGETS.pdfRangeMemoryCacheMaxBytes;
export const PDF_RANGE_POLICY_ERROR_CODE =
  READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.PDF_RANGE_PROTOCOL].errorCode;

export type PdfReaderErrorCode =
  | 'PDF_RANGE_UNSUPPORTED'
  | typeof PDF_RANGE_POLICY_ERROR_CODE
  | 'PDF_RESOURCE_CHANGED'
  | 'NETWORK_UNAVAILABLE'
  | 'PDF_CACHE_IO'
  | 'PDF_INVALID'
  | 'PDF_PAGE_LOAD_FAILED'
  | 'PDF_RENDER_FAILED'
  | 'OUT_OF_MEMORY_RISK';

export type PdfByteRange = Readonly<{ begin: number; end: number }>;

/** Quantizes a PDF page's intra-page progression to the shared wire precision. */
export function quantizePageProgression(value: number): number {
  return Math.round(Math.max(0, Math.min(1, value)) * 10_000) / 10_000;
}

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
