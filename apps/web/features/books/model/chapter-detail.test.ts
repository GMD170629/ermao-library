import assert from 'node:assert/strict';
import test from 'node:test';
import type { ReadableResourceView } from '../../../types/book';
import { detailReaderHref, singleResourceEbook, syntheticPdfPageUnits } from './chapter-detail';

function resource(overrides: Partial<ReadableResourceView> = {}): ReadableResourceView {
  return {
    id: 'resource-1', bookId: 'book-1', sourceNodeId: 'resource-1-source-node', title: '第一卷', description: '', resourceIndex: 1, sortOrder: 0,
    format: 'EPUB', readerType: 'reflowable', classification: { source: 'AUTO', reason: 'FORMAT_DEFAULT', suggestedMediaKind: null }, publisher: null, publishedAt: null, language: null,
    isbn: null, identifier: null, narrator: null, abridged: null, importStatus: 'READY', importError: null,
    coverUrl: '', sizeBytes: 0, pageCount: null, chapterCount: 3, durationMs: null, trackCount: null, progress: 0,
    lastReadAt: null, hidden: false, readable: true, kindleSendAvailable: true, assets: [], ...overrides
  };
}

test('single-resource chapter detail follows the reader type instead of classification', () => {
  const onlyResource = resource();
  assert.equal(singleResourceEbook([onlyResource]), onlyResource);
  assert.equal(singleResourceEbook([resource({ format: 'MP3', readerType: 'audio' })]), null);
  assert.equal(singleResourceEbook([onlyResource, resource({ id: 'resource-2' })]), null);
});

test('chapter targets use exact reflowable hrefs and PDF page numbers', () => {
  assert.equal(detailReaderHref(resource(), { id: 'chapter-1', title: '第一章', href: 'Text/ch1.xhtml', sortOrder: 0, unitType: 'chapter', pageNumber: null }), '/reader/resource-1?href=Text%2Fch1.xhtml');
  assert.equal(detailReaderHref(resource({ format: 'PDF' }), { id: 'page-7', title: '第 7 页', href: null, sortOrder: 6, unitType: 'page', pageNumber: 7 }), '/reader/resource-1?page=7');
});

test('PDF detail pages are generated in bounded page-sized slices', () => {
  const units = syntheticPdfPageUnits(resource({ format: 'PDF', pageCount: 245 }), 3, 120);
  assert.equal(units.length, 5);
  assert.equal(units[0]?.pageNumber, 241);
  assert.equal(units[4]?.pageNumber, 245);
});
