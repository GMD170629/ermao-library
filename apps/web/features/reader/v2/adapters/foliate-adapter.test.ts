import assert from 'node:assert/strict';
import test from 'node:test';
import {
  foliateNavigationEntries,
  normalizeFoliateInitialLocation,
  parseFoliateRelocateDetail
} from './foliate-adapter';

test('parseFoliateRelocateDetail validates CFI and clamps official fraction', () => {
  assert.deepEqual(
    parseFoliateRelocateDetail({ cfi: 'epubcfi(/6/2!/4/1:2)', fraction: 1.4, range: {} }),
    { cfi: 'epubcfi(/6/2!/4/1:2)', fraction: 1, tocItem: undefined }
  );
  assert.deepEqual(parseFoliateRelocateDetail({ fraction: -0.2 }), {
    cfi: undefined,
    fraction: 0,
    tocItem: undefined
  });
  assert.equal(parseFoliateRelocateDetail({ cfi: '', fraction: Number.NaN }), null);
  assert.equal(parseFoliateRelocateDetail('invalid'), null);
});

test('normalizeFoliateInitialLocation migrates legacy EPUB locations without losing fallbacks', () => {
  assert.deepEqual(normalizeFoliateInitialLocation({
    kind: 'epub',
    cfi: 'epubcfi(/6/4)',
    href: 'chapter.xhtml',
    spineIndex: 3,
    progression: 0.42
  }, 'epub'), {
    kind: 'reflowable',
    format: 'epub',
    cfi: 'epubcfi(/6/4)',
    href: 'chapter.xhtml',
    progression: 0.42
  });
  assert.equal(normalizeFoliateInitialLocation({ kind: 'pdf', pageNumber: 2 }, 'epub'), null);
});

test('foliateNavigationEntries maps nested official TOC data and rejects malformed items', () => {
  assert.deepEqual(foliateNavigationEntries([
    { label: ' Part 1 ', href: 'part-1', subitems: [{ label: 'Chapter', href: 'chapter' }] },
    { label: 123, href: 'ignored' }
  ]), [{
    id: 'toc-0',
    label: 'Part 1',
    href: 'part-1',
    children: [{ id: 'toc-0-0', label: 'Chapter', href: 'chapter', children: undefined }]
  }]);
});
