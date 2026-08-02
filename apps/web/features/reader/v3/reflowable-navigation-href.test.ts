import assert from 'node:assert/strict';
import test from 'node:test';
import { isEngineResolvableReflowableHref } from './reflowable-navigation-href';

test('blocks only known import pseudo-hrefs', () => {
  assert.equal(isEngineResolvableReflowableHref('mobi', 'mobi-section:4'), false);
  assert.equal(isEngineResolvableReflowableHref('txt', 'txt-chapter:0'), false);
  assert.equal(isEngineResolvableReflowableHref('fb2', 'fb2-section:1'), false);
});

test('passes through foliate-native and EPUB hrefs unchanged', () => {
  assert.equal(isEngineResolvableReflowableHref('mobi', 'filepos:1234'), true);
  assert.equal(isEngineResolvableReflowableHref('azw3', 'kindle:pos:fid:0001:off:0000000000'), true);
  assert.equal(isEngineResolvableReflowableHref('epub', 'OEBPS/text00003.html'), true);
  assert.equal(isEngineResolvableReflowableHref('epub', 'Text/all.xhtml#chapter-2'), true);
  assert.equal(isEngineResolvableReflowableHref('fb2', '#section-1'), true);
});

test('empty hrefs are never resolvable', () => {
  assert.equal(isEngineResolvableReflowableHref('mobi', null), false);
  assert.equal(isEngineResolvableReflowableHref('epub', '  '), false);
});
