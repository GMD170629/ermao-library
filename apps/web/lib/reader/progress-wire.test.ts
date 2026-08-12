import assert from 'node:assert/strict';
import test from 'node:test';
import {
  parseV4Location,
  remoteLocationMatchesPublication,
  toV4WireLocation,
  v4LocationToDomain
} from './progress-wire';

test('Foliate remote locator restores engine details before public anchors and percent', () => {
  const remote = parseV4Location({
    kind: 'reflow',
    resourceKey: 'text/chapter-12.xhtml',
    progression: 0.43,
    position: 1842,
    textQuote: { exact: '一段短文本' },
    engineLocator: {
      engine: 'foliate',
      platform: 'web',
      version: '1',
      payload: { cfi: 'epubcfi(/6/24!/4/2)', fraction: 0.327 }
    }
  });
  const location = v4LocationToDomain(remote, 'volume-1', 'epub', 32.7);
  assert.deepEqual(location, {
    kind: 'reflowable',
    format: 'epub',
    cfi: 'epubcfi(/6/24!/4/2)',
    href: 'text/chapter-12.xhtml',
    resourceProgression: 0.43,
    position: 1842,
    textQuote: { exact: '一段短文本' },
    progression: 0.327,
    foliate: { continuous: { sectionFraction: 0.43 } }
  });
});

test('Web extracts a recognizable CFI from a Readium engine payload', () => {
  const remote = parseV4Location({
    kind: 'reflow',
    engineLocator: {
      engine: 'readium',
      platform: 'android',
      version: '3.8.0',
      payload: { locations: { fragments: ['epubcfi(/6/8!/4/2)'] } }
    }
  });
  const location = v4LocationToDomain(remote, 'volume-1', 'epub', 20);
  assert.equal(location?.kind === 'reflowable' ? location.cfi : null, 'epubcfi(/6/8!/4/2)');
  assert.equal(location?.kind === 'reflowable' ? location.progression : null, 0.2);
});

test('a mismatched original file hash suppresses exact anchors but missing hashes do not', () => {
  const local = {
    originalFileHash: 'sha256:local',
    parserVersion: 'foliate-web-v1',
    normalizationVersion: 'shuku-reader-v4'
  };
  const remote = parseV4Location({
    kind: 'reflow',
    resourceKey: 'chapter.xhtml',
    contentFingerprint: {
      originalFileHash: 'sha256:remote',
      parserVersion: 'readium-3.8',
      normalizationVersion: 'v1'
    }
  });
  assert.equal(remoteLocationMatchesPublication(remote, local), false);
  assert.equal(remoteLocationMatchesPublication(remote, undefined), true);
  assert.equal(remoteLocationMatchesPublication({ kind: 'reflow', resourceKey: 'chapter.xhtml' }, local), true);
});

test('oversized engine payload is neither uploaded nor accepted', () => {
  const huge = 'x'.repeat(65 * 1024);
  assert.equal(parseV4Location({
    kind: 'reflow',
    engineLocator: {
      engine: 'foliate',
      platform: 'web',
      version: '1',
      payload: { huge }
    }
  }), null);
  assert.equal(toV4WireLocation({
    kind: 'reflowable',
    format: 'epub',
    foliate: { toc: { index: 1, title: huge } }
  }), null);
});
