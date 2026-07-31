import assert from 'node:assert/strict';
import test from 'node:test';

import {
  compareStableVersions,
  extractLocalizedReleaseNote,
  parseStableVersion,
  validateApplicationVersions,
  validateReleaseMarkdown,
  validateReleaseIndex
} from './validate-release-notes.mjs';

const validIndex = {
  schemaVersion: 1,
  repository: 'GMD170629/ermao-library',
  releases: [
    {
      version: '1.2.3',
      tag: 'v1.2.3',
      publishedAt: '2026-07-29T00:00:00Z',
      notesPath: 'v1.2.3.md',
      releaseUrl: 'https://github.com/GMD170629/ermao-library/releases/tag/v1.2.3'
    },
    {
      version: '1.2.2',
      tag: 'v1.2.2',
      publishedAt: '2026-07-28T00:00:00Z',
      notesPath: 'v1.2.2.md',
      releaseUrl: 'https://github.com/GMD170629/ermao-library/releases/tag/v1.2.2'
    }
  ]
};

test('stable version parsing and comparison reject prereleases', () => {
  assert.deepEqual(parseStableVersion('1.2.3'), [1, 2, 3]);
  assert.equal(parseStableVersion('v1.2.3'), null);
  assert.equal(parseStableVersion('1.2.3-beta.1'), null);
  assert.ok(compareStableVersions('2.0.0', '1.99.99') > 0);
  assert.equal(compareStableVersions('1.2.3', '1.2.3'), 0);
});

test('localized release note extraction requires exact markers', () => {
  const markdown = [
    '<!-- shuku:locale=zh-CN:start -->',
    '中文说明',
    '<!-- shuku:locale=zh-CN:end -->',
    '<!-- shuku:locale=en-US:start -->',
    'English notes',
    '<!-- shuku:locale=en-US:end -->'
  ].join('\n');
  assert.equal(extractLocalizedReleaseNote(markdown, 'zh-CN'), '中文说明');
  assert.equal(extractLocalizedReleaseNote(markdown, 'en-US'), 'English notes');
  assert.throws(() => extractLocalizedReleaseNote(markdown, 'fr-FR'), /Missing or malformed/u);
});

test('release index requires a unique descending stable history', () => {
  assert.equal(validateReleaseIndex(structuredClone(validIndex), '1.2.3').length, 2);

  const duplicate = structuredClone(validIndex);
  duplicate.releases[1] = { ...duplicate.releases[0] };
  assert.throws(() => validateReleaseIndex(duplicate, '1.2.3'), /Duplicate/u);

  const ascending = structuredClone(validIndex);
  ascending.releases.reverse();
  assert.throws(() => validateReleaseIndex(ascending, '1.2.2'), /descending/u);

  const wrongTag = structuredClone(validIndex);
  wrongTag.releases[0].tag = 'release-1.2.3';
  assert.throws(() => validateReleaseIndex(wrongTag, '1.2.3'), /tag must/u);
});

function bilingualNote(zhCN, enUS) {
  return [
    '# v1.2.3',
    '',
    '<!-- shuku:locale=zh-CN:start -->',
    '## 简体中文',
    '',
    zhCN,
    '<!-- shuku:locale=zh-CN:end -->',
    '',
    '<!-- shuku:locale=en-US:start -->',
    '## English',
    '',
    enUS,
    '<!-- shuku:locale=en-US:end -->',
    ''
  ].join('\n');
}

test('release Markdown requires substantive distinct bilingual notes without placeholders', () => {
  const valid = bilingualNote(
    '本版本增加严格的双语发布说明校验，并确保所有正式发布路径都使用同一个权威来源，从流程上阻止遗漏说明的版本公开发布。',
    'This release adds strict bilingual note validation and makes every formal publishing path use one authoritative source.'
  );
  assert.doesNotThrow(() => validateReleaseMarkdown(valid, '1.2.3', 'v1.2.3.md'));
  assert.throws(
    () => validateReleaseMarkdown(valid.replace(/<!-- shuku:locale=en-US:start -->[\s\S]*<!-- shuku:locale=en-US:end -->/u, ''), '1.2.3', 'v1.2.3.md'),
    /en-US/u
  );
  assert.throws(
    () => validateReleaseMarkdown(bilingualNote('待补充正式的中文发布说明内容，这段文字刻意增加长度以确认占位符检查不会被最小长度检查掩盖。', 'A complete English release note is available for this version and contains enough detail for validation.'), '1.2.3', 'v1.2.3.md'),
    /placeholder/u
  );
  const identical = 'This shared text is deliberately long enough to be substantive, and it also contains 中文 characters for both checks.';
  assert.throws(() => validateReleaseMarkdown(bilingualNote(identical, identical), '1.2.3', 'v1.2.3.md'), /must not be identical/u);
});

test('application version sources and release tags must exactly match', () => {
  const versions = {
    root: '1.2.3',
    web: '1.2.3',
    mobile: '1.2.3',
    mobileRuntime: '1.2.3',
    python: '1.2.3',
    runtime: '1.2.3',
    uvLock: '1.2.3'
  };
  assert.doesNotThrow(() => validateApplicationVersions(versions, 'v1.2.3'));
  assert.throws(() => validateApplicationVersions({ ...versions, runtime: '1.2.2' }), /version mismatch/u);
  assert.throws(() => validateApplicationVersions(versions, 'v1.2.4'), /does not match/u);
});
