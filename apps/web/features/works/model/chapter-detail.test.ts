import assert from 'node:assert/strict';
import test from 'node:test';
import type { VolumeResource } from '../../../types/work';
import { detailReaderHref, singleVolumeEbook, syntheticPdfPageUnits } from './chapter-detail';

function volume(overrides: Partial<VolumeResource> = {}): VolumeResource {
  return {
    id: 'volume-1', versionId: 'version-1', title: '第一卷', volumeIndex: 1, sortOrder: 0,
    format: 'EPUB', readerType: 'reflowable', classification: { source: 'LEGACY', reason: 'LEGACY', suggestedMediaKind: null }, derivedFromVolumeId: null, publisher: null, publishedAt: null, language: null,
    isbn: null, identifier: null, narrator: null, abridged: null, importStatus: 'READY', importError: null,
    coverUrl: '', sizeBytes: 0, pageCount: null, chapterCount: 3, durationMs: null, trackCount: null, progress: 0,
    lastReadAt: null, hidden: false, readable: true, kindleSendAvailable: true, files: [], ...overrides
  };
}

test('single-volume chapter detail follows the reader type instead of classification', () => {
  const onlyVolume = volume();
  assert.equal(singleVolumeEbook([onlyVolume]), onlyVolume);
  assert.equal(singleVolumeEbook([volume({ format: 'MP3', readerType: 'audio' })]), null);
  assert.equal(singleVolumeEbook([onlyVolume, volume({ id: 'volume-2' })]), null);
});

test('chapter targets use exact reflowable hrefs and PDF page numbers', () => {
  assert.equal(detailReaderHref(volume(), { id: 'chapter-1', title: '第一章', href: 'Text/ch1.xhtml', sortOrder: 0, unitType: 'chapter', pageNumber: null }), '/reader/volume-1?href=Text%2Fch1.xhtml');
  assert.equal(detailReaderHref(volume({ format: 'PDF' }), { id: 'page-7', title: '第 7 页', href: null, sortOrder: 6, unitType: 'page', pageNumber: 7 }), '/reader/volume-1?page=7');
});

test('PDF detail pages are generated in bounded page-sized slices', () => {
  const units = syntheticPdfPageUnits(volume({ format: 'PDF', pageCount: 245 }), 3, 120);
  assert.equal(units.length, 5);
  assert.equal(units[0]?.pageNumber, 241);
  assert.equal(units[4]?.pageNumber, 245);
});
