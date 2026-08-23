import assert from 'node:assert/strict';
import test from 'node:test';
import type { ReadableResourceView } from '../../../types/book';
import { resourceDetailItemHref, resourceDetailPageSize } from './resource-detail';

function resource(overrides: Partial<ReadableResourceView>): ReadableResourceView {
  return {
    id: 'resource-1', bookId: 'book-1', sourceNodeId: 'node-1', title: 'Resource', description: '', resourceIndex: null,
    sortOrder: 0, format: 'EPUB', readerType: 'reflowable', classification: { source: 'AUTO', reason: 'FORMAT_DEFAULT', suggestedMediaKind: null },
    publisher: null, publishedAt: null, language: null, isbn: null, identifier: null, narrator: null, abridged: null,
    importStatus: 'READY', importError: null, coverUrl: '', sizeBytes: 0, pageCount: null, chapterCount: null,
    durationMs: null, trackCount: null, progress: 0, lastReadAt: null, hidden: false, readable: true, kindleSendAvailable: false, assets: [],
    ...overrides
  };
}

test('uses preview pagination for comic and PDF resources', () => {
  assert.equal(resourceDetailPageSize(resource({ format: 'PDF', readerType: 'pdf' })), 24);
  assert.equal(resourceDetailPageSize(resource({ format: 'IMAGE_DIR', readerType: 'comic' })), 24);
  assert.equal(resourceDetailPageSize(resource({ format: 'AUDIOBOOK_DIR', readerType: 'audio' })), 50);
});

test('builds exact chapter, page and stable audio track links', () => {
  const epub = resource({ format: 'EPUB' });
  assert.equal(resourceDetailItemHref(epub, { id: 'chapter', unitType: 'chapter', title: 'One', sortOrder: 0, assetId: null, mediaType: null, href: 'Text/one.xhtml', level: 0 }), '/reader/resource-1?href=Text%2Fone.xhtml');
  assert.equal(resourceDetailItemHref(resource({ format: 'PDF', readerType: 'pdf' }), { id: 'page', unitType: 'page', title: '', sortOrder: 8, assetId: null, mediaType: 'application/pdf', pageNumber: 9, previewUrl: '/preview' }), '/reader/resource-1?page=9');
  assert.equal(resourceDetailItemHref(resource({ format: 'AUDIOBOOK_DIR', readerType: 'audio' }), { id: 'track', unitType: 'track', title: 'Track', sortOrder: 0, assetId: 'asset 1', mediaType: 'audio/mpeg', durationMs: null, discNumber: null, trackNumber: null }), '/listen/resource-1?assetId=asset%201');
});
