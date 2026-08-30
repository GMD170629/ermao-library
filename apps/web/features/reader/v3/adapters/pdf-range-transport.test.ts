import assert from 'node:assert/strict';
import test from 'node:test';
import {
  PDF_RANGE_CHUNK_BYTES,
  PDF_RANGE_MAX_REQUEST_BYTES,
  READER_SAFETY_RULE_IDS,
  planPdfByteRanges
} from '@shuku/reader-core';
import { PdfRangeByteSource, PdfRangeError, type PdfRangeAccess } from './pdf-range-transport';
import { ReaderSafetyPolicyError } from '../security/reader-safety-policy';

const ETAG = '"2097135-1786742400"';

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

  };
}

function rangeResponse(bytes: Uint8Array, init?: RequestInit) {
  const headers = new Headers({
    'Accept-Ranges': 'bytes',
    ETag: ETAG,
    'Content-Type': 'application/pdf',
    'Content-Encoding': 'identity',
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

test('does not decide PDF validity from a file signature', async () => {
  const bytes = fixtureBytes();
  bytes.fill(0, 0, 1024);
  const source = new PdfRangeByteSource(access(bytes), async (_input, init) => rangeResponse(bytes, init));
  assert.deepEqual(await source.prepare(new AbortController().signal), bytes.slice(0, PDF_RANGE_CHUNK_BYTES));
  source.abort();
});

test('HEAD denial retains its real HTTP reason without consuming a body', async () => {
  let cancelled = false;
  const source = new PdfRangeByteSource(access(fixtureBytes()), async () => new Response(
    new ReadableStream({ cancel() { cancelled = true; } }), { status: 403 },
  ));
  await assert.rejects(source.prepare(new AbortController().signal), { code: 'FORBIDDEN', stage: 'pdf' });
  assert.equal(cancelled, true);
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

test('strong ETag becomes the If-Range validator and oversized reads send no extra request', async () => {
  const bytes = fixtureBytes();
  let requests = 0;
  const source = new PdfRangeByteSource(access(bytes), async (_input, init) => {
    if (init?.method !== 'HEAD') {
      requests += 1;
      assert.equal(new Headers(init?.headers).get('If-Range'), ETAG);
    }
    return rangeResponse(bytes, init);
  });
  await source.prepare(new AbortController().signal);
  await assert.rejects(
    source.read(0, PDF_RANGE_MAX_REQUEST_BYTES + 1),
    (reason: unknown) => reason instanceof PdfRangeError
      && reason.code === 'PDF_RANGE_INVALID'
      && reason.ruleId === READER_SAFETY_RULE_IDS.PDF_RANGE_PROTOCOL
  );
  assert.equal(requests, 1);
  source.abort();
});

test('HEAD admission rejects weak revisions and wrong MIME through their generated rules', async () => {
  const bytes = fixtureBytes();
  const weakRevision = new PdfRangeByteSource(access(bytes), async (_input, init) => {
    const response = rangeResponse(bytes, init);
    response.headers.set('ETag', `W/${ETAG}`);
    return response;
  });
  await assert.rejects(
    weakRevision.prepare(new AbortController().signal),
    (reason: unknown) => reason instanceof PdfRangeError
      && reason.ruleId === READER_SAFETY_RULE_IDS.PDF_RANGE_PROTOCOL
  );

  const wrongMime = new PdfRangeByteSource(access(bytes), async (_input, init) => {
    const response = rangeResponse(bytes, init);
    response.headers.set('Content-Type', 'application/octet-stream');
    return response;
  });
  await assert.rejects(
    wrongMime.prepare(new AbortController().signal),
    (reason: unknown) => reason instanceof ReaderSafetyPolicyError
      && reason.ruleId === READER_SAFETY_RULE_IDS.COMMON_EXACT_FORMAT_MIME
  );
});

test('rejects a silent full-file fallback through the generated PDF Range rule', async () => {
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
    (reason: unknown) => reason instanceof PdfRangeError
      && reason.code === 'PDF_RANGE_INVALID'
      && reason.ruleId === READER_SAFETY_RULE_IDS.PDF_RANGE_PROTOCOL
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

test('ignored Range cancels before reading a body that never completes', async () => {
  const bytes = fixtureBytes();
  let cancelled = false;
  let pulls = 0;
  const source = new PdfRangeByteSource(access(bytes), async (_input, init) => {
    if (init?.method === 'HEAD') return rangeResponse(bytes, init);
    return new Response(new ReadableStream({
      pull() { pulls += 1; }, cancel() { cancelled = true; }
    }, { highWaterMark: 0 }), { status: 200 });
  });
  await assert.rejects(source.prepare(new AbortController().signal), /服务器未返回 PDF Range 响应/);
  assert.equal(pulls, 0);
  assert.equal(cancelled, true);
  assert.equal(source.metrics().transferredBytes, 0);
});

test('closing a session cancels access and reopening cannot use its body cache', async () => {
  const bytes = fixtureBytes();
  let requests = 0;
  const fetcher: typeof fetch = async (_input, init) => {
    if (init?.method !== 'HEAD') requests += 1;
    return rangeResponse(bytes, init);
  };
  const source = new PdfRangeByteSource(access(bytes), fetcher);
  await source.prepare(new AbortController().signal);
  source.abort();
  await assert.rejects(source.read(0, 8), { name: 'AbortError' });
  const reopened = new PdfRangeByteSource(access(bytes), fetcher);
  await reopened.prepare(new AbortController().signal);
  assert.equal(requests, 2);
});
