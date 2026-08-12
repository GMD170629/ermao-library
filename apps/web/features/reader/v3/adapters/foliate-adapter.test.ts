import assert from 'node:assert/strict';
import test from 'node:test';
import {
  foliateNavigationEntries,
  foliateResolvedSectionIndex,
  foliateRemainingSeconds,
  foliateSectionIndexFromDisplayIndex,
  normalizeFoliateInitialLocation,
  parseFoliateRelocateDetail,
  refineContinuousRestoreWithSectionFraction,
  resolveFoliatePaginatedRestoreTargets,
  resolveAsynchronousFoliateHref,
  shouldRefineContinuousRestoreWithProgression,
  shouldResolveFoliateTocItem,
  validatedServerToc
} from './foliate-adapter';
import { resolveReflowableDocumentLink } from './reflowable-continuous';

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

test('converts Foliate minute estimates to the seconds used by Reader v4', () => {
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

test('continuous document links resolve a section-normalized string through the book', async () => {
  const target = { index: 4, anchor: () => null };
  const result = await resolveReflowableDocumentLink({
    sections: [{
      load: () => '',
      resolveHref: (href) => `OEBPS/${href}`
    }],
    resolveHref: (href) => href === 'OEBPS/index_split_004.html#filepos62933' ? target : undefined
  }, 0, 'index_split_004.html#filepos62933');

  assert.deepEqual(result, target);
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

test('pagination restores a section CFI without evaluating an empty content anchor', async () => {
  const unsafeAnchor = () => { throw new TypeError('Invalid empty CFI content path'); };
  const targets = await resolveFoliatePaginatedRestoreTargets({
    sections: [{ load: () => '' }, { id: 'chapter-2.xhtml', load: () => '' }],
    resolveCFI: () => ({ index: 1, anchor: unsafeAnchor }),
    resolveHref: () => ({ index: 1, anchor: () => 0 })
  }, {
    kind: 'reflowable',
    format: 'epub',
    cfi: 'epubcfi(/6/4)',
    href: 'chapter-2.xhtml',
    progression: 0.5,
    foliate: { section: { current: 1, total: 2 } }
  });

  assert.deepEqual(targets[0], { index: 1 });
  assert.notEqual(targets[0]?.anchor, unsafeAnchor);
  assert.deepEqual(targets.slice(1).map(({ index }) => index), [1, 1]);
});

test('pagination preserves a full content CFI anchor and rejects invalid restore targets', async () => {
  const anchor = () => 0;
  const targets = await resolveFoliatePaginatedRestoreTargets({
    sections: [{ load: () => '' }, { load: () => '' }],
    resolveCFI: () => ({ index: 1, anchor }),
    resolveHref: () => ({ index: 8 })
  }, {
    kind: 'reflowable',
    format: 'epub',
    cfi: 'epubcfi(/6/4!/4/2/2)',
    href: 'missing.xhtml',
    foliate: { section: { current: 0, total: 2 } }
  });

  assert.deepEqual(targets, [{ index: 1, anchor }, { index: 0 }]);
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

test('continuous restore refines chapter-only resume locations with saved progression', () => {
  assert.equal(shouldRefineContinuousRestoreWithProgression({
    kind: 'reflowable',
    format: 'epub',
    cfi: 'epubcfi(/6/4)',
    href: 'chapter.xhtml',
    progression: 0.42
  }, { index: 1, anchor: () => null }), true);

  assert.equal(shouldRefineContinuousRestoreWithProgression({
    kind: 'reflowable',
    format: 'epub',
    cfi: 'epubcfi(/6/4!/4/2/2)',
    href: 'chapter.xhtml',
    progression: 0.42
  }, { index: 1, anchor: () => null }), false);

  assert.equal(shouldRefineContinuousRestoreWithProgression({
    kind: 'reflowable',
    format: 'epub',
    href: 'chapter.xhtml#paragraph-8',
    progression: 0.42
  }, { index: 1, anchor: () => null }), false);

  assert.deepEqual(refineContinuousRestoreWithSectionFraction({
    kind: 'reflowable',
    format: 'epub',
    cfi: 'epubcfi(/6/4)',
    href: 'chapter.xhtml',
    progression: 0.42,
    foliate: { continuous: { sectionFraction: 0.68 } }
  }, { index: 1, anchor: () => null }), { index: 1, fraction: 0.68 });
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

test('does not resolve a fixed-layout section CFI as a text range', () => {
  assert.equal(shouldResolveFoliateTocItem({
    cfi: 'epubcfi(/6/2)',
    fraction: 0.01
  }, true), false);
});

test('keeps TOC lookup for reflowable content CFIs without an official TOC item', () => {
  assert.equal(shouldResolveFoliateTocItem({
    cfi: 'epubcfi(/6/2!/4/1:2)',
    fraction: 0.01
  }, false), true);
  assert.equal(shouldResolveFoliateTocItem({
    cfi: 'epubcfi(/6/2!/4/1:2)',
    fraction: 0.01,
    tocItem: { label: 'Chapter 1' }
  }, false), false);
});
