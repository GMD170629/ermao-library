import {
  PDF_RANGE_CHUNK_BYTES,
  PDF_RANGE_MAX_CONCURRENT_REQUESTS,
  PDF_RANGE_MAX_REQUEST_BYTES,
  PDF_RANGE_MEMORY_CACHE_BYTES,
  pdfRangeChunkKey,
  type PdfRangeCacheIdentity,
  type PdfReaderErrorCode
} from '@shuku/reader-core';
import type { PDFDataRangeTransport } from 'pdfjs-dist/legacy/build/pdf.mjs';
import type { PdfRangeCache } from '../../../../lib/reader/pdf-range-cache';

type PdfJsModule = typeof import('pdfjs-dist/legacy/build/pdf.mjs');

export type PdfRangeAccess = Readonly<{
  url: string;
  length: number;
  identity: PdfRangeCacheIdentity;
  cache: PdfRangeCache;
}>;

export type PdfRangeMetrics = Readonly<{
  requestCount: number;
  transferredBytes: number;
  cacheHits: number;
  cacheMisses: number;
  firstByteMilliseconds: number | null;
}>;

export class PdfRangeError extends Error {
  constructor(readonly code: PdfReaderErrorCode, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = 'PdfRangeError';
  }
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

  constructor(
    private readonly access: PdfRangeAccess,
    private readonly fetcher: typeof globalThis.fetch = globalThis.fetch.bind(globalThis)
  ) {
    if (!Number.isSafeInteger(access.length) || access.length <= 0) {
      throw new PdfRangeError('PDF_RANGE_INVALID', 'PDF 文件大小无效');
    }
  }

  get length() {
    return this.access.length;
  }

  async prepare(signal: AbortSignal): Promise<Uint8Array> {
    await this.validateHead(signal);
    const bytes = await this.read(0, Math.min(PDF_RANGE_CHUNK_BYTES, this.access.length), signal);
    const prefix = new TextDecoder('latin1').decode(bytes.subarray(0, Math.min(bytes.byteLength, 1024)));
    if (!prefix.includes('%PDF-')) throw new PdfRangeError('PDF_INVALID', 'PDF 文件格式无效或已经损坏');
    return bytes;
  }

  async read(begin: number, end: number, signal: AbortSignal = this.abortController.signal): Promise<Uint8Array> {
    if (!Number.isSafeInteger(begin) || !Number.isSafeInteger(end)
      || begin < 0 || end <= begin || end > this.access.length) {
      throw new PdfRangeError('PDF_RANGE_INVALID', 'PDF 字节区间无效');
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
    if (written !== result.byteLength) throw new PdfRangeError('PDF_RANGE_INVALID', 'PDF Range 响应不完整');
    return result;
  }

  abort() {
    this.abortController.abort();
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
        signal
      });
    } catch (cause) {
      throw new PdfRangeError('NETWORK_UNAVAILABLE', 'PDF 网络请求失败', { cause });
    }
    if (!response.ok) throw new PdfRangeError('NETWORK_UNAVAILABLE', `PDF 文件读取失败 (${response.status})`);
    if (!response.headers.get('Accept-Ranges')?.toLowerCase().split(',').map((value) => value.trim()).includes('bytes')) {
      throw new PdfRangeError('PDF_RANGE_UNSUPPORTED', '服务器不支持 PDF 字节 Range');
    }
    const length = Number(response.headers.get('Content-Length'));
    if (!Number.isSafeInteger(length) || length !== this.access.length) {
      throw new PdfRangeError('PDF_RESOURCE_CHANGED', 'PDF 文件大小已经变化');
    }
  }

  private async loadCachedChunk(index: number) {
    const existing = this.memory.get(index);
    if (existing) {
      this.cacheHits += 1;
      this.touchMemory(index, existing.bytes);
      return true;
    }
    try {
      const cached = await this.access.cache.getPdfRangeChunk(this.access.identity, index);
      if (!cached) {
        this.cacheMisses += 1;
        return false;
      }
      this.cacheHits += 1;
      this.touchMemory(index, cached.bytes);
      return true;
    } catch (cause) {
      throw new PdfRangeError('PDF_CACHE_IO', 'PDF 分块缓存读取失败', { cause });
    }
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
      const group = [fresh[offset]!];
      offset += 1;
      while (offset < fresh.length && group.length < maxChunks
        && fresh[offset] === group[group.length - 1]! + 1) {
        group.push(fresh[offset]!);
        offset += 1;
      }
      const request = this.scheduler.run(() => this.fetchChunkGroup(group, signal));
      group.forEach((index) => this.inFlight.set(index, request));
      void request.finally(() => group.forEach((index) => {
        if (this.inFlight.get(index) === request) this.inFlight.delete(index);
      })).catch(() => undefined);
      waiting.add(request);
    }
    await Promise.all(waiting);
  }

  private async fetchChunkGroup(indices: number[], signal: AbortSignal) {
    this.assertNotAborted(signal);
    const begin = indices[0]! * PDF_RANGE_CHUNK_BYTES;
    const end = Math.min(this.access.length, (indices[indices.length - 1]! + 1) * PDF_RANGE_CHUNK_BYTES);
    let response: Response;
    this.requestCount += 1;
    try {
      response = await this.fetcher(this.access.url, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Range: `bytes=${begin}-${end - 1}` },
        signal
      });
    } catch (cause) {
      throw new PdfRangeError('NETWORK_UNAVAILABLE', 'PDF 网络请求失败', { cause });
    }
    if (response.status === 200) {
      throw new PdfRangeError('PDF_RANGE_UNSUPPORTED', '服务器未返回 PDF Range 响应');
    }
    if (response.status === 416) throw new PdfRangeError('PDF_RANGE_INVALID', '服务器拒绝了 PDF 字节区间');
    if (response.status !== 206) throw new PdfRangeError('NETWORK_UNAVAILABLE', `PDF Range 请求失败 (${response.status})`);
    if (response.headers.get('Content-Range') !== `bytes ${begin}-${end - 1}/${this.access.length}`) {
      throw new PdfRangeError('PDF_RANGE_INVALID', 'PDF Content-Range 与请求不一致');
    }
    const payload = new Uint8Array(await response.arrayBuffer());
    if (payload.byteLength !== end - begin) throw new PdfRangeError('PDF_RANGE_INVALID', 'PDF Range 长度与请求不一致');
    this.transferredBytes += payload.byteLength;
    this.firstByteAt ??= Date.now();
    for (const index of indices) {
      const chunkBegin = index * PDF_RANGE_CHUNK_BYTES - begin;
      const chunkEnd = Math.min(payload.byteLength, chunkBegin + PDF_RANGE_CHUNK_BYTES);
      const bytes = payload.slice(chunkBegin, chunkEnd);
      this.touchMemory(index, bytes);
      try {
        await this.access.cache.putPdfRangeChunk(
          this.access.identity,
          index,
          bytes,
          [...this.memory.keys()].map((chunkIndex) => pdfRangeChunkKey(this.access.identity, chunkIndex))
        );
      } catch (cause) {
        throw new PdfRangeError('PDF_CACHE_IO', 'PDF 分块缓存写入失败', { cause });
      }
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
