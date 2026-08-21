import assert from 'node:assert/strict';
import test from 'node:test';
import {
  PDF_RANGE_CHUNK_BYTES,
  PDF_RANGE_MAX_REQUEST_BYTES,
  planPdfByteRanges
} from '@shuku/reader-core';
import { MemoryReaderStorage } from '../../../../lib/reader/memory-storage';
import { PdfRangeByteSource, PdfRangeError, type PdfRangeAccess } from './pdf-range-transport';

const ETAG = 'W/"2097135-1786742400"';

function fixtureBytes(chunkCount = 8) {
  const bytes = new Uint8Array(PDF_RANGE_CHUNK_BYTES * chunkCount - 17);
  bytes.set(new TextEncoder().encode('%PDF-1.7\n'));
  for (let index = 9; index < bytes.byteLength; index += 1) bytes[index] = index % 251;
  return bytes;
}

function access(bytes: Uint8Array): PdfRangeAccess {
  return {
    url: '/api/assets/asset-1',
    length: bytes.byteLength,
    identity: {
      serverIdentity: 'https://reader.test',
      userId: 'user-1',
      authorizationVersion: 3,
      resourceId: 'resource-1'
    },
    cache: new MemoryReaderStorage()
  };
}

function rangeResponse(bytes: Uint8Array, init?: RequestInit) {
  const headers = new Headers({
    'Accept-Ranges': 'bytes',
    ETag: ETAG,
    'Content-Length': String(bytes.byteLength)
  });
  if (init?.method === 'HEAD') return new Response(null, { status: 200, headers });
  const match = /^bytes=(\d+)-(\d+)$/u.exec(new Headers(init?.headers).get('Range') ?? '');
  assert.ok(match);
  const begin = Number(match[1]);
  const end = Number(match[2]);
  headers.set('Content-Range', `bytes ${begin}-${end}/${bytes.byteLength}`);
  headers.set('Content-Length', String(end - begin + 1));
  return new Response(bytes.slice(begin, end + 1), { status: 206, headers });
}

test('aligns PDF byte requests to 256 KiB and caps requests at one MiB', () => {
  const ranges = planPdfByteRanges(7, PDF_RANGE_MAX_REQUEST_BYTES + 7, PDF_RANGE_MAX_REQUEST_BYTES * 2);
  assert.deepEqual(ranges, [
    { begin: 0, end: PDF_RANGE_MAX_REQUEST_BYTES },
    { begin: PDF_RANGE_MAX_REQUEST_BYTES, end: PDF_RANGE_MAX_REQUEST_BYTES + PDF_RANGE_CHUNK_BYTES }
  ]);
});

test('uses only validated 206 responses and reuses cached chunks', async () => {
  const bytes = fixtureBytes();
  const requests: string[] = [];
  const source = new PdfRangeByteSource(access(bytes), async (_input, init) => {
    if (init?.method !== 'HEAD') requests.push(new Headers(init?.headers).get('Range') ?? '');
    return rangeResponse(bytes, init);
  });
  await source.prepare(new AbortController().signal);
  const begin = PDF_RANGE_CHUNK_BYTES * 3 + 31;
  const end = PDF_RANGE_CHUNK_BYTES * 5 + 47;
  const first = await source.read(begin, end);
  const second = await source.read(begin, end);
  assert.deepEqual(first, bytes.slice(begin, end));
  assert.deepEqual(second, first);
  assert.deepEqual(requests, [
    `bytes=0-${PDF_RANGE_CHUNK_BYTES - 1}`,
    `bytes=${PDF_RANGE_CHUNK_BYTES * 3}-${PDF_RANGE_CHUNK_BYTES * 6 - 1}`
  ]);
  const metrics = source.metrics();
  assert.equal(metrics.requestCount, 2);
  assert.equal(metrics.transferredBytes, PDF_RANGE_CHUNK_BYTES * 4);
  assert.ok(metrics.cacheHits >= 3);
  assert.ok(metrics.cacheMisses >= 4);
  assert.ok(metrics.firstByteMilliseconds !== null && metrics.firstByteMilliseconds >= 0);
});

test('rejects a silent full-file fallback with PDF_RANGE_UNSUPPORTED', async () => {
  const bytes = fixtureBytes(2);
  const source = new PdfRangeByteSource(access(bytes), async (_input, init) => {
    if (init?.method === 'HEAD') return rangeResponse(bytes, init);
    return new Response(bytes, {
      status: 200,
      headers: { 'Accept-Ranges': 'bytes', ETag: ETAG, 'Content-Length': String(bytes.byteLength) }
    });
  });
  await assert.rejects(
    source.prepare(new AbortController().signal),
    (reason: unknown) => reason instanceof PdfRangeError && reason.code === 'PDF_RANGE_UNSUPPORTED'
  );
});

test('limits concurrent network ranges to two requests', async () => {
  const bytes = fixtureBytes(9);
  let active = 0;
  let maximum = 0;
  const source = new PdfRangeByteSource(access(bytes), async (_input, init) => {
    if (init?.method === 'HEAD') return rangeResponse(bytes, init);
    active += 1;
    maximum = Math.max(maximum, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active -= 1;
    return rangeResponse(bytes, init);
  });
  await source.prepare(new AbortController().signal);
  await Promise.all([2, 4, 6].map((index) => source.read(
    index * PDF_RANGE_CHUNK_BYTES,
    (index + 1) * PDF_RANGE_CHUNK_BYTES
  )));
  assert.equal(maximum, 2);
});
