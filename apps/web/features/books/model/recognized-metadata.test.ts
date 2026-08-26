import assert from 'node:assert/strict';
import test from 'node:test';
import type { BookView, ReadableResourceView } from '../../../types/book';
import type { SourceNodeMetadataCandidate } from './book-contents';
import {
  defaultRecognizedMetadataFields,
  hasMetadataValue,
  recognizedMetadataFields
} from './recognized-metadata';

const resource: ReadableResourceView = {
  id: 'resource-1', bookId: 'book-1', sourceNodeId: 'node-1', title: '第一卷', description: '',
  resourceIndex: 1, sortOrder: 0, format: 'EPUB', readerType: 'reflowable', publisher: null,
  publishedAt: null, language: null, isbn: null, identifier: null, narrator: null, abridged: null,
  importStatus: 'READY', importError: null, coverUrl: '', sizeBytes: 100, pageCount: null,
  chapterCount: 1, durationMs: null, trackCount: null, progress: 0, lastReadAt: null,
  hidden: false, readable: true, kindleSendAvailable: false, assets: []
};

const book: BookView = {
  id: 'book-1', sourceNodeId: 'root-1', title: '旧标题', author: '同一作者', description: '',
  seriesName: null, seriesIndex: null, tags: ['科幻'], publicationStatus: 'UNKNOWN',
  trackingStatus: 'NOT_TRACKING', ignored: false, organized: false, metadataQuality: 0,
  addedAt: '', updatedAt: '', coverUrl: '', coverStatus: 'PENDING', gradient: '',
  continueResourceId: 'resource-1', completed: false, resources: [resource],
  resourceImportSummary: { ready: 1, pending: 0, failed: 0 }
};

const candidate: SourceNodeMetadataCandidate = {
  id: 'candidate-1', source: 'douban', title: '新标题', author: '同一作者',
  description: '简介', tags: ['科幻'], seriesName: '系列', seriesIndex: 2,
  publisher: '出版社', publishedAt: '2026-08-26T00:00:00Z', language: 'zh-CN',
  isbn: '9780000000001', identifier: 'subject:1', narrator: null, abridged: false,
  resourceIndex: 2, coverUrl: 'https://example.test/cover.jpg', confidence: 0.9
};

test('whole-book recognition exposes every supported book field', () => {
  assert.deepEqual(recognizedMetadataFields('book').map(({ field }) => field), [
    'book.title', 'book.author', 'book.description', 'book.seriesName',
    'book.seriesIndex', 'book.tags', 'book.cover'
  ]);
});

test('resource recognition groups linked book fields and all resource metadata', () => {
  const definitions = recognizedMetadataFields('resource');
  assert.deepEqual(definitions.filter(({ group }) => group === 'book').map(({ field }) => field), [
    'book.author', 'book.seriesName', 'book.seriesIndex', 'book.tags'
  ]);
  assert.deepEqual(definitions.filter(({ group }) => group === 'resource').map(({ field }) => field), [
    'resource.title', 'resource.description', 'resource.publisher', 'resource.publishedAt',
    'resource.language', 'resource.isbn', 'resource.identifier', 'resource.narrator',
    'resource.abridged', 'resource.resourceIndex', 'resource.cover'
  ]);
});

test('defaults select only non-empty candidate values that differ from current state', () => {
  const selected = defaultRecognizedMetadataFields(
    book,
    resource,
    candidate,
    recognizedMetadataFields('resource')
  );

  assert.equal(selected.includes('book.author'), false);
  assert.equal(selected.includes('book.tags'), false);
  assert.equal(selected.includes('resource.narrator'), false);
  assert.equal(selected.includes('resource.abridged'), true);
  assert.equal(selected.includes('resource.publisher'), true);
  assert.equal(selected.includes('resource.cover'), true);
  assert.equal(hasMetadataValue(false), true);
});
