import assert from 'node:assert/strict';
import test from 'node:test';
import { parseV4Location, v4LocationToDomain } from '../../../lib/reader';

test('v4 comic wire locations inherit the volume-scoped endpoint identity', () => {
  const wire = parseV4Location({ kind: 'comic', pageIndex: 7 });
  assert.deepEqual(
    v4LocationToDomain(wire, 'volume-2', null, 50),
    { kind: 'comic', volumeId: 'volume-2', pageIndex: 7 }
  );
});

test('v4 public reflow anchors map without accepting retired v3 fields', () => {
  const wire = parseV4Location({
    kind: 'reflow',
    resourceKey: 'chapter.xhtml',
    progression: 0.65,
    engineLocator: {
      engine: 'foliate',
      platform: 'web',
      version: 'foliate-web-v1',
      payload: { cfi: 'epubcfi(/6/4)' }
    }
  });
  assert.deepEqual(
    v4LocationToDomain(wire, 'volume-1', 'mobi', 40),
    {
      kind: 'reflowable',
      format: 'mobi',
      cfi: 'epubcfi(/6/4)',
      href: 'chapter.xhtml',
      resourceProgression: 0.65,
      progression: 0.4,
      foliate: { continuous: { sectionFraction: 0.65 } }
    }
  );
  assert.equal(parseV4Location({ type: 'epub', href: 'chapter.xhtml' }), null);
});
