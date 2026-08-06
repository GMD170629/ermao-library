import assert from 'node:assert/strict';
import test from 'node:test';
import { wireLocationToDomain } from './api';

test('comic wire locations inherit the volume-scoped endpoint identity', () => {
  assert.deepEqual(
    wireLocationToDomain({ type: 'comic', pageIndex: 7 }, 'volume-2'),
    { kind: 'comic', volumeId: 'volume-2', pageIndex: 7 }
  );
});

test('maps new and legacy EPUB wire anchors to the reflowable domain', () => {
  assert.deepEqual(
    wireLocationToDomain({
      type: 'reflowable',
      format: 'mobi',
      cfi: 'epubcfi(/6/4)',
      progression: 0.4,
      foliate: { continuous: { sectionFraction: 0.65 } }
    }, 'volume-1'),
    {
      kind: 'reflowable',
      format: 'mobi',
      cfi: 'epubcfi(/6/4)',
      href: undefined,
      progression: 0.4,
      foliate: { continuous: { sectionFraction: 0.65 } }
    }
  );
  assert.deepEqual(
    wireLocationToDomain({ type: 'epub', cfi: 'epubcfi(/6/2)', href: 'chapter.xhtml' }, 'volume-1'),
    { kind: 'reflowable', format: 'epub', cfi: 'epubcfi(/6/2)', href: 'chapter.xhtml', progression: undefined }
  );
});
