import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import * as pdfjs from 'pdfjs-dist/legacy/build/pdf.mjs';
import { PDF_RANGE_CHUNK_BYTES } from '@shuku/reader-core';
import { createPdfJsRangeTransport, PdfRangeByteSource } from './pdf-range-transport';

const require = createRequire(import.meta.url);
pdfjs.GlobalWorkerOptions.workerSrc = pathToFileURL(require.resolve('pdfjs-dist/legacy/build/pdf.worker.mjs')).href;

function sparsePdf(): Uint8Array {
  const parts = ['%PDF-1.7\n'];
  const offsets = [0];
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>',
    '<< /Length 16 >>\nstream\n0 0 100 100 re S\nendstream',
  ];
  for (const [index, object] of objects.entries()) {
    offsets.push(parts.join('').length);
    parts.push(`${index + 1} 0 obj\n${object}\nendobj\n`);
  }
  // An unreferenced region is deliberately unavailable to the online transport.
  offsets.push(parts.join('').length);
  parts.push(`5 0 obj\n<< /Length ${24 * 1024 * 1024} >>\nstream\n${'x'.repeat(24 * 1024 * 1024)}\nendstream\nendobj\n`);
  const xref = parts.join('').length;
  parts.push('xref\n0 6\n0000000000 65535 f \n');
  for (const offset of offsets.slice(1)) parts.push(`${String(offset).padStart(10, '0')} 00000 n \n`);
  parts.push(`trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`);
  return new TextEncoder().encode(parts.join(''));
}

test('pinned PDF renderer opens and renders with all non-current content blocked', { timeout: 10000 }, async () => {
  const bytes = sparsePdf();
  const requested: Array<[number, number]> = [];
  const fetcher: typeof fetch = async (_input, init) => {
    if (init?.method === 'HEAD') return new Response(null, { headers: {
      'Accept-Ranges': 'bytes', 'Content-Length': String(bytes.length), 'Content-Type': 'application/pdf',
      ETag: '"pdf-online-fixture-v1"',
    } });
    const range = new Headers(init?.headers).get('range');
    assert.ok(range, 'the reader must never request a complete original');
    const match = /^bytes=(\d+)-(\d+)$/.exec(range);
    assert.ok(match);
    const begin = Number(match[1]);
    const end = Number(match[2]) + 1;
    assert.ok(end - begin <= 1024 * 1024);
    assert.ok(begin < PDF_RANGE_CHUNK_BYTES || begin >= Math.floor((bytes.length - 1024) / PDF_RANGE_CHUNK_BYTES) * PDF_RANGE_CHUNK_BYTES,
      'a non-current body range was requested');
    requested.push([begin, end]);
    return new Response(bytes.slice(begin, end), { status: 206, headers: {
      'Content-Range': `bytes ${begin}-${end - 1}/${bytes.length}`,
      'Content-Length': String(end - begin), 'Content-Type': 'application/pdf',
      ETag: '"pdf-online-fixture-v1"',
    } });
  };
  const source = new PdfRangeByteSource({ url: '/api/assets/pdf', length: bytes.length }, fetcher);
  const initial = await source.prepare(new AbortController().signal);
  const failures: Error[] = [];
  const range = createPdfJsRangeTransport(pdfjs, source, initial, (error) => failures.push(error));
  const task = pdfjs.getDocument({ range, rangeChunkSize: PDF_RANGE_CHUNK_BYTES,
    disableStream: true, disableAutoFetch: true, stopAtErrors: true });
  try {
    const publication = await task.promise;
    assert.equal(publication.numPages, 1);
    await source.activateUnit(0);
    await publication.setReadingWindow(0);
    const page = await publication.getPage(1);
    const operators = await page.getOperatorList();
    assert.ok(operators.fnArray.length > 0);
    assert.deepEqual(failures, []);
    assert.ok(requested.reduce((total, [begin, end]) => total + end - begin, 0) < 1024 * 1024);
  } finally { await task.destroy(); source.abort(); }
});
