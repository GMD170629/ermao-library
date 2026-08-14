import assert from 'node:assert/strict';
import test from 'node:test';
import {
  compareExactReadiumLocators,
  isExactReadiumLocatorEnvelope,
  parsePublicationLocation,
  parseReadiumLocatorEnvelope,
  type ReadiumLocatorEnvelope
} from '@shuku/reader-core';
import exactRequest from '../../../../packages/reader-contracts/fixtures/exact-reflowable-request.json';
import progressionOnly from '../../../../packages/reader-contracts/fixtures/progression-only-invalid.json';
import { parseReaderV4ProgressSnapshot, v4LocationToDomain } from './progress-wire';

const wire = parsePublicationLocation(exactRequest.locator);
if (!wire || wire.kind !== 'reflowable') throw new Error('invalid exact fixture');
const exact = { ...wire.engineLocator, publication: wire.publication } satisfies ReadiumLocatorEnvelope;

test('accepts the canonical cross-language exact locator fixture', () => {
  assert.equal(isExactReadiumLocatorEnvelope(exact), true);
  assert.deepEqual(parseReadiumLocatorEnvelope(exact), exact);
});

test('rejects progression-only and mismatched publication fingerprints as exact', () => {
  assert.equal(isExactReadiumLocatorEnvelope(progressionOnly.locator), false);
  const mismatch = { ...exact, publication: { ...exact.publication, normalization: 'different-v2' } };
  assert.deepEqual(compareExactReadiumLocators(exact, mismatch), {
    precision: 'unverified', sameResource: true, reason: 'fingerprint_mismatch'
  });
});

test('counts text bounds as Unicode code points and rejects malformed portable fields', () => {
  const locator = (highlight: unknown) => ({
    ...exact,
    payload: { ...exact.payload, text: { highlight } }
  });
  assert.notEqual(parseReadiumLocatorEnvelope(locator('😀'.repeat(512))), null);
  assert.equal(parseReadiumLocatorEnvelope(locator('😀'.repeat(513))), null);
  assert.equal(parseReadiumLocatorEnvelope({
    ...exact,
    payload: { ...exact.payload, locations: { ...exact.payload.locations, position: 1.5 } }
  }), null);
  assert.equal(parseReadiumLocatorEnvelope({
    ...exact,
    payload: { ...exact.payload, href: '../outside.xhtml' }
  }), null);
});

test('requires href plus the same selector, fragment, or normalized text after navigation', () => {
  const sameText = {
    ...exact,
    payload: {
      ...exact.payload,
      locations: { progression: 0.45 },
      text: { highlight: '天地玄黄，宇宙洪荒', before: '前文', after: '后文' }
    }
  } as ReadiumLocatorEnvelope;
  assert.equal(compareExactReadiumLocators(exact, sameText).precision, 'exact-block');
  assert.equal(compareExactReadiumLocators(exact, { ...sameText, payload: { ...sameText.payload, href: 'part00001.html' } }).precision, 'unverified');
});

test('parses only exact v4 snapshots and never restores from display percent', () => {
  const snapshot = parseReaderV4ProgressSnapshot({ schemaVersion: 4, clientId: 'ios-client', revision: 18, locator: wire, displayPercent: 32.7, receivedAtEpochMillis: 1786500000100, capturedAtEpochMillis: 1786499999000 });
  assert.equal(snapshot?.revision, 18);
  assert.equal(snapshot?.capturedAtEpochMillis, 1786499999000);
  assert.equal(v4LocationToDomain(snapshot?.locator ?? null, 'volume-1', 'mobi')?.kind, 'reflowable');
  assert.equal(parseReaderV4ProgressSnapshot({ schemaVersion: 4, clientId: 'ios-client', revision: 18, locator: progressionOnly.locator, displayPercent: 32.7, receivedAtEpochMillis: 1786500000100 }), null);
});
