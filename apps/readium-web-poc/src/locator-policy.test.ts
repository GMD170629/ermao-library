import assert from 'node:assert/strict';
import test from 'node:test';
import {
  boundedText,
  compareAnchors,
  compareFingerprints,
  TEXT_QUOTE_MAX_LENGTH,
  utf8Length
} from './locator-policy';

test('bounds long CJK block text to the wire-safe quote limit', () => {
  const bounded = boundedText('长'.repeat(100_000));
  assert.equal(bounded?.length, TEXT_QUOTE_MAX_LENGTH);
  assert.equal(utf8Length(bounded ?? ''), TEXT_QUOTE_MAX_LENGTH * 3);
});

test('matching selectors are exact while progression-only matches are approximate', () => {
  const exact = { href: 'part00000.html', cssSelector: '#anchor', progression: 0.5 };
  assert.equal(compareAnchors(exact, exact).precision, 'exact-block');
  assert.equal(compareAnchors(
    { href: 'part00000.html', progression: 0.5 },
    { href: 'part00000.html', progression: 0.51 }
  ).precision, 'approximate-resource');
});

test('different resources never report an exact match', () => {
  const result = compareAnchors(
    { href: 'part00000.html', cssSelector: '#same' },
    { href: 'part00001.html', cssSelector: '#same' }
  );
  assert.equal(result.precision, 'fallback');
  assert.equal(result.sameResource, false);
});

test('exact anchors require the complete structured fingerprint to match', () => {
  const fingerprint = {
    originalFileHash: 'f2b9',
    parser: 'libmobi:0.12',
    normalization: 'ermao-mobi-core-v1+shuku-locator-dom-v2'
  };
  assert.equal(compareFingerprints(fingerprint, fingerprint), 'match');
  assert.equal(compareFingerprints(fingerprint, { ...fingerprint, normalization: 'other' }), 'mismatch');
  assert.equal(compareFingerprints(fingerprint, undefined), 'missing');
});
