import assert from 'node:assert/strict';
import test from 'node:test';
import {
  appendTagValues,
  normalizeTagValue,
  parseTagValues,
  tagValuesOverlap,
  uniqueTagValues
} from './tag-values';

test('parses pasted tag values across supported separators', () => {
  assert.deepEqual(
    parseTagValues('科幻, 待读；年度精选\n中文，短篇'),
    ['科幻', '待读', '年度精选', '中文', '短篇']
  );
});

test('normalizes Unicode, casing, whitespace, and facet punctuation like the backend', () => {
  assert.equal(normalizeTagValue(' ＳＣＩ－ＦＩ '), normalizeTagValue('sci fi'));
  assert.equal(normalizeTagValue('龙族【完结】'), normalizeTagValue('龙族 完结'));
});

test('deduplicates normalized values while preserving the first display spelling', () => {
  assert.deepEqual(
    uniqueTagValues([' Sci-Fi ', 'sci fi', '', '待  阅读', '待 阅读']),
    ['Sci-Fi', '待 阅读']
  );
  assert.deepEqual(appendTagValues(['Fantasy'], ['fantasy', 'New']), ['Fantasy', 'New']);
});

test('reports normalized overlap without changing either collection', () => {
  const additions = ['科幻', 'Sci-Fi'];
  const removals = ['sci fi', '临时'];
  assert.deepEqual(tagValuesOverlap(additions, removals), ['Sci-Fi']);
  assert.deepEqual(additions, ['科幻', 'Sci-Fi']);
  assert.deepEqual(removals, ['sci fi', '临时']);
});
