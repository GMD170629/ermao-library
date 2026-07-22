import assert from 'node:assert/strict';
import test from 'node:test';
import { approximateEpubProgression, classifyEpubHref, completedEpubProgression, epubRestoreTargets, resolveEpubDocumentHref, restoreEpubLocation, selectEpubTocHref, selectEpubVisibleResource } from './epub-restore';

test('EPUB restore always attempts CFI before structural and progression fallbacks', () => {
  assert.deepEqual(epubRestoreTargets({
    kind: 'epub',
    cfi: ' epubcfi(/6/2) ',
    href: 'chapter-2.xhtml',
    spineIndex: 3,
    progression: 1.4
  }), [
    { kind: 'cfi', value: 'epubcfi(/6/2)' },
    { kind: 'href', value: 'chapter-2.xhtml' },
    { kind: 'spine', value: 3 },
    { kind: 'progression', value: 1 },
    { kind: 'start' }
  ]);
});

test('EPUB restore advances after a rejected CFI', async () => {
  const attempted: string[] = [];
  const restored = await restoreEpubLocation({ kind: 'epub', cfi: 'bad-cfi', href: 'chapter.xhtml', progression: 0.5 }, async (target) => {
    attempted.push(target.kind);
    if (target.kind === 'cfi') throw new Error('invalid cfi');
  });
  assert.deepEqual(attempted, ['cfi', 'href']);
  assert.deepEqual(restored, { kind: 'href', value: 'chapter.xhtml' });
});

test('EPUB document links resolve relative to the current spine href', () => {
  assert.equal(resolveEpubDocumentHref('../Text/chapter-3.xhtml#note', 'OPS/Chapters/chapter-2.xhtml'), 'OPS/Text/chapter-3.xhtml#note');
  assert.equal(resolveEpubDocumentHref('#footnote', 'OPS/chapter.xhtml#old'), 'OPS/chapter.xhtml#footnote');
  assert.equal(resolveEpubDocumentHref('https://example.com/read', 'OPS/chapter.xhtml'), 'https://example.com/read');
});

test('EPUB links distinguish internal, user-opened external, and blocked schemes', () => {
  assert.deepEqual(classifyEpubHref('../chapter.xhtml#note'), { kind: 'internal', href: '../chapter.xhtml#note' });
  assert.deepEqual(classifyEpubHref('//example.com/read'), { kind: 'external', href: 'https://example.com/read' });
  assert.deepEqual(classifyEpubHref('mailto:reader@example.com'), { kind: 'external', href: 'mailto:reader@example.com' });
  assert.deepEqual(classifyEpubHref('tel:+8612345'), { kind: 'external', href: 'tel:+8612345' });
  assert.deepEqual(classifyEpubHref('javascript:alert(1)'), { kind: 'blocked', href: 'javascript:alert(1)' });
  assert.deepEqual(classifyEpubHref('data:text/plain,secret'), { kind: 'blocked', href: 'data:text/plain,secret' });
});

test('EPUB chapter href follows the last TOC anchor before the relocated CFI in a shared spine item', () => {
  const order = new Map([
    ['epubcfi(/6/2!/4/2)', 1],
    ['epubcfi(/6/2!/4/8)', 2],
    ['epubcfi(/6/2!/4/14)', 3],
    ['epubcfi(/6/2!/4/20)', 4]
  ]);
  const compare = (first: string, second: string) => (order.get(first) ?? 0) - (order.get(second) ?? 0);
  const href = selectEpubTocHref('Text/volume.xhtml', 'epubcfi(/6/2!/4/14)', [
    { href: 'Text/volume.xhtml#chapter-1', cfi: 'epubcfi(/6/2!/4/2)' },
    { href: 'Text/volume.xhtml#chapter-2', cfi: 'epubcfi(/6/2!/4/8)' },
    { href: 'Text/volume.xhtml#chapter-3', cfi: 'epubcfi(/6/2!/4/20)' },
    { href: 'Text/other.xhtml#chapter-4', cfi: 'epubcfi(/6/2!/4/2)' }
  ], compare);

  assert.equal(href, 'Text/volume.xhtml#chapter-2');
});

test('EPUB visible resource ignores edge-touching continuous neighbors', () => {
  assert.equal(selectEpubVisibleResource([
    { href: 'titlepage.xhtml', left: -1200, top: 0, right: 0, bottom: 900 },
    { href: 'text/part0000.html', left: 0, top: 0, right: 1200, bottom: 900 },
    { href: 'text/part0001.html', left: 1200, top: 0, right: 2400, bottom: 900 }
  ], { left: 0, top: 0, right: 1200, bottom: 900 }), 'text/part0000.html');
});

test('EPUB visible resource preserves the rendition preference for an equal double-page overlap', () => {
  assert.equal(selectEpubVisibleResource([
    { href: 'left.xhtml', left: 0, top: 0, right: 600, bottom: 900 },
    { href: 'right.xhtml', left: 600, top: 0, right: 1200, bottom: 900 }
  ], { left: 0, top: 0, right: 1200, bottom: 900 }, 'right.xhtml'), 'right.xhtml');
});

test('EPUB progress fallback combines spine index and section percentage', () => {
  assert.equal(approximateEpubProgression(3, 0.5, 10), 0.35);
  assert.equal(approximateEpubProgression(3, undefined, 10, 6, 10), 0.35);
  assert.equal(approximateEpubProgression(undefined, 0.5, 10), 0.5);
  assert.equal(approximateEpubProgression(9, 2, 10), 1);
});

test('EPUB reports the physical end of the rendition as completed', () => {
  assert.equal(completedEpubProgression(0.94, true), 1);
  assert.equal(completedEpubProgression(0.94, false), 0.94);
});
