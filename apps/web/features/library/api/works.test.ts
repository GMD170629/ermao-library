import assert from 'node:assert/strict';
import test from 'node:test';
import { libraryWorksUrl, mapLibraryWorkSummary } from './works';

test('library list selects the lightweight projection required by the active view', () => {
  const bookshelfUrl = new URL(
    libraryWorksUrl('q=example', 2, '50', 'bookshelf'),
    'http://localhost'
  );
  const managementUrl = new URL(
    libraryWorksUrl('q=example', 3, '20', 'management'),
    'http://localhost'
  );

  assert.equal(bookshelfUrl.searchParams.get('view'), 'bookshelf');
  assert.equal(bookshelfUrl.searchParams.get('page'), '2');
  assert.equal(managementUrl.searchParams.get('view'), 'management');
  assert.equal(managementUrl.searchParams.get('page'), '3');
});

test('management projection maps media and progress summaries without mediaVersions', () => {
  const work = mapLibraryWorkSummary({
    id: 'work-1',
    title: 'Example',
    author: 'Author',
    format: 'EPUB',
    gradient: 'from-slate-950',
    coverStatus: 'READY',
    coverUrl: '/api/works/work-1/cover',
    publisher: 'Publisher',
    seriesName: 'Series',
    tags: ['tag'],
    type: 'ebook',
    availableMediaKinds: ['EBOOK', 'AUDIOBOOK'],
    statusValue: 'READING',
    lastReadAt: '2026-08-01T00:00:00Z',
    importedAt: '2026-07-31T00:00:00Z'
  }, 'management');

  assert.equal(work.projection, 'management');
  if (work.projection !== 'management') assert.fail('expected management projection');
  assert.deepEqual(work.availableMediaKinds, ['EBOOK', 'AUDIOBOOK']);
  assert.equal(work.statusValue, 'READING');
  assert.equal('mediaVersions' in work, false);
});

test('management projection rejects a malformed media summary at the API boundary', () => {
  assert.throws(
    () => mapLibraryWorkSummary({ id: 'work-1' }, 'management'),
    /LIBRARY_WORK_SUMMARY_INVALID/
  );
});
