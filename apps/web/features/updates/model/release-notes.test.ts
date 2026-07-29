import assert from 'node:assert/strict';
import test from 'node:test';
import {
  compareStableVersions,
  extractLocalizedReleaseNote,
  parseReleaseFeed,
  parseStableVersion,
  updateStatus
} from './release-notes';

const feedPayload = {
  schemaVersion: 1,
  repository: 'GMD170629/ermao-library',
  releases: [
    {
      version: '1.2.3',
      tag: 'v1.2.3',
      publishedAt: '2026-07-29T00:00:00Z',
      notesPath: 'v1.2.3.md',
      releaseUrl: 'https://github.com/GMD170629/ermao-library/releases/tag/v1.2.3'
    }
  ]
};

test('stable versions exclude tags and prereleases', () => {
  assert.deepEqual(parseStableVersion('1.2.3'), [1, 2, 3]);
  assert.equal(parseStableVersion('v1.2.3'), null);
  assert.equal(parseStableVersion('1.2.3-rc.1'), null);
  assert.ok(compareStableVersions('2.0.0', '1.99.99') > 0);
});

test('release feed validates the external wire contract', () => {
  const feed = parseReleaseFeed(feedPayload);
  assert.equal(feed.releases[0].version, '1.2.3');
  assert.throws(() => parseReleaseFeed({ ...feedPayload, repository: 'other/repo' }), /格式无效/u);
  assert.throws(() => parseReleaseFeed({ ...feedPayload, releases: [feedPayload.releases[0], feedPayload.releases[0]] }), /重复/u);
});

test('update state distinguishes old, current, and development versions', () => {
  const feed = parseReleaseFeed(feedPayload);
  assert.equal(updateStatus('1.2.2', feed).kind, 'update-available');
  assert.equal(updateStatus('1.2.3', feed).kind, 'current');
  assert.equal(updateStatus('1.3.0', feed).kind, 'development');
});

test('localized release notes require the requested locale section', () => {
  const markdown = [
    '<!-- shuku:locale=zh-CN:start -->',
    '中文内容',
    '<!-- shuku:locale=zh-CN:end -->',
    '<!-- shuku:locale=en-US:start -->',
    'English content',
    '<!-- shuku:locale=en-US:end -->'
  ].join('\n');
  assert.equal(extractLocalizedReleaseNote(markdown, 'zh-CN'), '中文内容');
  assert.equal(extractLocalizedReleaseNote(markdown, 'en-US'), 'English content');
});
