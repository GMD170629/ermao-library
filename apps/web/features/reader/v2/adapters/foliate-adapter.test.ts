import assert from 'node:assert/strict';
import test from 'node:test';
import {
  foliateNavigationEntries,
  foliateResolvedSectionIndex,
  foliateRemainingSeconds,
  foliateSectionIndexFromDisplayIndex,
  normalizeFoliateInitialLocation,
  parseFoliateRelocateDetail,
  resolveAsynchronousFoliateHref,
  validatedServerToc
} from './foliate-adapter';

test('parseFoliateRelocateDetail validates CFI and clamps official fraction', () => {
  assert.deepEqual(
    parseFoliateRelocateDetail({ cfi: 'epubcfi(/6/2!/4/1:2)', fraction: 1.4, range: {} }),
    { cfi: 'epubcfi(/6/2!/4/1:2)', fraction: 1 }
  );
  assert.deepEqual(parseFoliateRelocateDetail({ fraction: -0.2 }), {
    fraction: 0
  });
  assert.equal(parseFoliateRelocateDetail({ cfi: '', fraction: Number.NaN }), null);
  assert.equal(parseFoliateRelocateDetail('invalid'), null);
});

test('parseFoliateRelocateDetail keeps validated official progress metrics', () => {
  const tocItem = { label: 'Chapter 2', href: 'chapter-2.xhtml' };
  assert.deepEqual(parseFoliateRelocateDetail({
    fraction: 0.425,
    tocItem,
    section: { current: 3, total: 12 },
    location: { current: 41, next: 43, total: 100 },
    time: { section: 180.5, total: 720.25 }
  }), {
    fraction: 0.425,
    tocItem,
    section: { current: 3, total: 12 },
    location: { current: 41, next: 43, total: 100 },
    time: { section: 180.5, total: 720.25 }
  });
  assert.deepEqual(parseFoliateRelocateDetail({
    fraction: 0.5,
    section: { current: 12, total: 12 },
    location: { current: -1, next: 2, total: 10 },
    time: { section: Number.NaN, total: 10 }
  }), { fraction: 0.5 });
});

test('converts Foliate minute estimates to the seconds used by Reader V2', () => {
  assert.deepEqual(foliateRemainingSeconds({ section: 2.5, total: 12 }), {
    section: 150,
    total: 720
  });
});

test('awaits asynchronous MOBI href resolution before renderer navigation', async () => {
  const target = { index: 2, anchor: () => null };
  const result = await resolveAsynchronousFoliateHref({
    sections: [{ load: () => '' }],
    resolveHref: async (href) => href === 'kindle:pos:fid:1:off:20' ? target : undefined
  }, 'kindle:pos:fid:1:off:20');
  assert.deepEqual(result, { asynchronous: true, target });
});

test('converts one-based directory labels to Foliate zero-based section indexes', () => {
  assert.equal(foliateSectionIndexFromDisplayIndex(1), 0);
  assert.equal(foliateSectionIndexFromDisplayIndex(2), 1);
});

test('falls back to the official href resolver when a MOBI TOC splitter rejects a target', async () => {
  const sectionIndex = await foliateResolvedSectionIndex({
    sections: [],
    splitTOCHref: () => { throw new Error('unsupported TOC href'); },
    resolveHref: async () => ({ index: 6, anchor: () => null })
  }, 'kindle:pos:fid:0001:off:0000000000');

  assert.equal(sectionIndex, 6);
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

test('validatedServerToc keeps only targets resolved by the current book', async () => {
  const book = {
    sections: [{ load: () => '' }, { load: () => '' }],
    resolveHref: (href: string) => href === 'filepos:20' ? { index: 1 } : { index: -1 }
  };

  const toc = await validatedServerToc(book, [
    { id: 'mobi:valid', navigationKey: 'mobi:valid', label: '第二节', href: 'filepos:20' },
    { id: 'mobi:invalid', navigationKey: 'mobi:invalid', label: '损坏章节', href: 'filepos:9999' }
  ]);

  assert.deepEqual(toc, [
    { label: '第二节', href: 'filepos:20', navigationKey: 'mobi:valid' }
  ]);
});
