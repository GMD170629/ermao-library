import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_FORMATS,
  READER_SAFETY_RULE_IDS,
  READER_SAFETY_RULES,
  readerSafetyAcceptsMimeType,
  type PdfReaderErrorCode,
  type ReaderSafetyRuleId
} from '@shuku/reader-core';
import type { PDFDataRangeTransport } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { readBoundedResponse } from '../../../../shared/api/bounded-response';
import { readerResourceFailure, requestReaderResource } from '../../api/client';
import {
  readerSafetyFailure,
  rejectReaderSafety
} from '../security/reader-safety-policy';

type PdfJsModule = typeof import('pdfjs-dist/legacy/build/pdf.mjs');

const PDF_RANGE_CHUNK_BYTES = READER_SAFETY_BUDGETS.pdfRangeChunkBytes;
const PDF_RANGE_MAX_CONCURRENT_REQUESTS = READER_SAFETY_BUDGETS.pdfRangeMaxConcurrent;
const PDF_RANGE_MAX_REQUEST_BYTES = READER_SAFETY_BUDGETS.pdfRangeRequestMaxBytes;
const PDF_RANGE_MEMORY_CACHE_BYTES = READER_SAFETY_BUDGETS.pdfRangeMemoryCacheMaxBytes;

export type PdfRangeAccess = Readonly<{
  url: string;
  length: number;
}>;

export type PdfRangeMetrics = Readonly<{
  requestCount: number;
  transferredBytes: number;
  cacheHits: number;
  cacheMisses: number;
  firstByteMilliseconds: number | null;
}>;

export class PdfRangeError extends Error {
  constructor(
    readonly code: PdfReaderErrorCode,
    message: string,
    options?: ErrorOptions,
    readonly ruleId: ReaderSafetyRuleId | null = null
  ) {
    super(message, options);
    this.name = 'PdfRangeError';
  }
}

function pdfRangePolicyError(message: string, options?: ErrorOptions): PdfRangeError {
  const failure = readerSafetyFailure(READER_SAFETY_RULE_IDS.PDF_RANGE_PROTOCOL);
  const errorCode = READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.PDF_RANGE_PROTOCOL].errorCode;
  if (failure.code !== errorCode) throw new Error('PLATFORM_POLICY_BINDING_INVALID');
  return new PdfRangeError(
    errorCode,
    message,
    options,
    failure.ruleId
  );
}

function identityEncoded(response: Response): boolean {
  const value = response.headers.get('Content-Encoding')?.trim().toLowerCase();
  return !value || value === 'identity';
}

class RequestScheduler {
  private active = 0;
  private readonly waiters: Array<() => void> = [];

  async run<T>(action: () => Promise<T>): Promise<T> {
    if (this.active >= PDF_RANGE_MAX_CONCURRENT_REQUESTS) {
      await new Promise<void>((resolve) => this.waiters.push(resolve));
    }
    this.active += 1;
    try {
      return await action();
    } finally {
      this.active -= 1;
      this.waiters.shift()?.();
    }
  }
}

type MemoryChunk = { bytes: Uint8Array; lastAccessedAt: number };

export class PdfRangeByteSource {
  private readonly scheduler = new RequestScheduler();
  private readonly memory = new Map<number, MemoryChunk>();
  private readonly inFlight = new Map<number, Promise<void>>();
  private readonly abortController = new AbortController();
  private readonly startedAt = Date.now();
  private requestCount = 0;
  private transferredBytes = 0;
  private cacheHits = 0;
  private cacheMisses = 0;
  private firstByteAt: number | null = null;
  private activePage: number | null = null;
  private revision: string | null = null;
  private revisionHeader: 'ETag' | 'X-Asset-Version' | null = null;
  private ifRange: string | null = null;

  constructor(
    private readonly access: PdfRangeAccess,
    private readonly fetcher: typeof globalThis.fetch = requestReaderResource
  ) {
    if (!Number.isSafeInteger(access.length) || access.length <= 0) {
      throw pdfRangePolicyError('PDF 文件大小无效');
    }
    if (access.length > READER_SAFETY_BUDGETS.originalMaxBytes) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_ORIGINAL_MAX_BYTES);
    }
  }

  get length() {
    return this.access.length;
  }

  async prepare(signal: AbortSignal): Promise<Uint8Array> {
    await this.validateHead(signal);
    const bytes = await this.read(0, Math.min(PDF_RANGE_CHUNK_BYTES, this.access.length), signal);
    return bytes;
  }

  async read(begin: number, end: number, signal: AbortSignal = this.abortController.signal): Promise<Uint8Array> {
    if (!Number.isSafeInteger(begin) || !Number.isSafeInteger(end)
      || begin < 0 || end <= begin || end > this.access.length || end - begin > PDF_RANGE_MAX_REQUEST_BYTES) {
      throw pdfRangePolicyError('PDF 字节区间无效');
    }
    this.assertNotAborted(signal);
    const firstChunk = Math.floor(begin / PDF_RANGE_CHUNK_BYTES);
    const finalChunk = Math.floor((end - 1) / PDF_RANGE_CHUNK_BYTES);
    const missing: number[] = [];
    for (let index = firstChunk; index <= finalChunk; index += 1) {
      if (!await this.loadCachedChunk(index)) missing.push(index);
    }
    await this.fetchMissingChunks(missing, signal);
    this.assertNotAborted(signal);
    const result = new Uint8Array(end - begin);
    let written = 0;
    for (let index = firstChunk; index <= finalChunk; index += 1) {
      const chunk = this.memory.get(index);
      if (!chunk) throw new PdfRangeError('PDF_CACHE_IO', 'PDF 分块缓存读取失败');
      this.touchMemory(index, chunk.bytes);
      const chunkBegin = index * PDF_RANGE_CHUNK_BYTES;
      const sliceBegin = Math.max(begin, chunkBegin) - chunkBegin;
      const sliceEnd = Math.min(end, chunkBegin + chunk.bytes.byteLength) - chunkBegin;
      result.set(chunk.bytes.subarray(sliceBegin, sliceEnd), written);
      written += sliceEnd - sliceBegin;
    }
    if (written !== result.byteLength) throw pdfRangePolicyError('PDF Range 响应不完整');
    return result;
  }

  async activateUnit(pageIndex: number): Promise<void> {
    if (this.activePage === pageIndex) return;
    this.activePage = pageIndex;
    // Complete the existing bounded responses before releasing their cache ownership.
    await Promise.allSettled([...this.inFlight.values()]);
    this.memory.clear();
  }

  abort() {
    this.abortController.abort();
    this.memory.clear();
    this.inFlight.clear();
  }

  metrics(): PdfRangeMetrics {
    return {
      requestCount: this.requestCount,
      transferredBytes: this.transferredBytes,
      cacheHits: this.cacheHits,
      cacheMisses: this.cacheMisses,
      firstByteMilliseconds: this.firstByteAt === null ? null : this.firstByteAt - this.startedAt
    };
  }

  private async validateHead(signal: AbortSignal) {
    let response: Response;
    try {
      response = await this.fetcher(this.access.url, {
        method: 'HEAD',
        credentials: 'same-origin',
        cache: 'no-store',
        signal: AbortSignal.any([signal, this.abortController.signal])
      });
    } catch (cause) {
      throw new PdfRangeError('NETWORK_UNAVAILABLE', 'PDF 网络请求失败', { cause });
    }
    if (!response.ok) throw await readerResourceFailure(response, 'pdf');
    if (!readerSafetyAcceptsMimeType(READER_SAFETY_FORMATS.PDF, response.headers.get('Content-Type') ?? '')) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_EXACT_FORMAT_MIME);
    }
    if (!identityEncoded(response)) {
      throw pdfRangePolicyError('PDF 响应的内容编码无效');
    }
    if (!response.headers.get('Accept-Ranges')?.toLowerCase().split(',').map((value) => value.trim()).includes('bytes')) {
      throw pdfRangePolicyError('服务器不支持 PDF 字节 Range');
    }
    const etag = response.headers.get('ETag');
    const explicitVersion = response.headers.get('X-Asset-Version');
    if (etag && !etag.startsWith('W/')) {
      this.revision = etag;
      this.revisionHeader = 'ETag';
      this.ifRange = etag;
    } else if (explicitVersion?.trim()) {
      this.revision = explicitVersion;
      this.revisionHeader = 'X-Asset-Version';
      this.ifRange = null;
    } else {
      throw pdfRangePolicyError('PDF 响应缺少强版本标识');
    }
    const length = Number(response.headers.get('Content-Length'));
    if (!Number.isSafeInteger(length) || length !== this.access.length) {
      throw pdfRangePolicyError('PDF 文件大小已经变化');
    }
  }

  private async loadCachedChunk(index: number) {
    const existing = this.memory.get(index);
    if (existing) {
      this.cacheHits += 1;
      this.touchMemory(index, existing.bytes);
      return true;
    }
    this.cacheMisses += 1;
    return false;
  }

  private async fetchMissingChunks(indices: number[], signal: AbortSignal) {
    const waiting = new Set<Promise<void>>();
    const fresh = indices.filter((index) => {
      const existing = this.inFlight.get(index);
      if (existing) waiting.add(existing);
      return !existing;
    });
    const maxChunks = PDF_RANGE_MAX_REQUEST_BYTES / PDF_RANGE_CHUNK_BYTES;
    for (let offset = 0; offset < fresh.length;) {
      const first = fresh[offset];
      if (first === undefined) break;
      const group = [first];
      offset += 1;
      while (offset < fresh.length && group.length < maxChunks
        && fresh[offset] === first + group.length) {
        group.push(first + group.length);
        offset += 1;
      }
      const request = this.scheduler.run(() => this.fetchChunkGroup(group, signal)).finally(() => {
        group.forEach((index) => { if (this.inFlight.get(index) === request) this.inFlight.delete(index); });
      });
      group.forEach((index) => this.inFlight.set(index, request));
      waiting.add(request);
    }
    await Promise.all(waiting);
  }

  private async fetchChunkGroup(indices: number[], signal: AbortSignal) {
    this.assertNotAborted(signal);
    const first = indices[0];
    const last = indices.at(-1);
    if (first === undefined || last === undefined) return;
    const begin = first * PDF_RANGE_CHUNK_BYTES;
    const end = Math.min(this.access.length, (last + 1) * PDF_RANGE_CHUNK_BYTES);
    let response: Response;
    this.requestCount += 1;
    try {
      response = await this.fetcher(this.access.url, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Range: `bytes=${begin}-${end - 1}`, ...(this.ifRange ? { 'If-Range': this.ifRange } : {}) },
        signal: AbortSignal.any([signal, this.abortController.signal])
      });
    } catch (cause) {
      throw new PdfRangeError('NETWORK_UNAVAILABLE', 'PDF 网络请求失败', { cause });
    }
    let rejection: PdfRangeError | null = null;
    if (response.status === 200) rejection = pdfRangePolicyError('服务器未返回 PDF Range 响应');
    else if (response.status === 416) rejection = pdfRangePolicyError('服务器拒绝了 PDF 字节区间');
    else if (response.status !== 206) throw await readerResourceFailure(response, 'pdf');
    else if (!readerSafetyAcceptsMimeType(READER_SAFETY_FORMATS.PDF, response.headers.get('Content-Type') ?? '')) {
      await response.body?.cancel();
      rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_EXACT_FORMAT_MIME);
    }
    else if (!identityEncoded(response)) {
      rejection = pdfRangePolicyError('PDF Range 的内容编码无效');
    }
    else if (response.headers.get('Content-Range') !== `bytes ${begin}-${end - 1}/${this.access.length}`) {
      rejection = pdfRangePolicyError('PDF Content-Range 与请求不一致');
    }
    if (!rejection && this.revision && this.revisionHeader
      && response.headers.get(this.revisionHeader) !== this.revision) {
      rejection = pdfRangePolicyError('PDF 文件版本已经变化');
    }
    if (rejection) { await response.body?.cancel(rejection); throw rejection; }
    let payload: Uint8Array;
    try { payload = await readBoundedResponse(response, PDF_RANGE_MAX_REQUEST_BYTES, end - begin); }
    catch (cause) { throw pdfRangePolicyError('PDF Range 长度与请求不一致', { cause }); }
    this.assertNotAborted(signal);
    this.transferredBytes += payload.byteLength;
    this.firstByteAt ??= Date.now();
    for (const index of indices) {
      const chunkBegin = index * PDF_RANGE_CHUNK_BYTES - begin;
      const chunkEnd = Math.min(payload.byteLength, chunkBegin + PDF_RANGE_CHUNK_BYTES);
      const bytes = payload.slice(chunkBegin, chunkEnd);
      this.touchMemory(index, bytes);

    }
  }

  private touchMemory(index: number, bytes: Uint8Array) {
    this.memory.delete(index);
    this.memory.set(index, { bytes, lastAccessedAt: Date.now() });
    let total = [...this.memory.values()].reduce((sum, chunk) => sum + chunk.bytes.byteLength, 0);
    for (const [candidate, chunk] of this.memory) {
      if (total <= PDF_RANGE_MEMORY_CACHE_BYTES) break;
      if (candidate === index) continue;
      this.memory.delete(candidate);
      total -= chunk.bytes.byteLength;
    }
  }

  private assertNotAborted(signal: AbortSignal) {
    if (signal.aborted || this.abortController.signal.aborted) throw new DOMException('PDF Range request aborted', 'AbortError');
  }
}

export function createPdfJsRangeTransport(
  pdfjs: PdfJsModule,
  source: PdfRangeByteSource,
  initialData: Uint8Array,
  onError: (error: PdfRangeError) => void
): PDFDataRangeTransport {
  class ReaderPdfRangeTransport extends pdfjs.PDFDataRangeTransport {
    requestDataRange(begin: number, end: number) {
      void source.read(begin, end).then((bytes) => this.onDataRange(begin, bytes)).catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return;
        onError(reason instanceof PdfRangeError
          ? reason
          : new PdfRangeError('NETWORK_UNAVAILABLE', 'PDF Range 请求失败', { cause: reason }));
      });
    }

    abort() {
      source.abort();
      super.abort();
    }
  }
  return new ReaderPdfRangeTransport(source.length, initialData.slice(), false);
}
