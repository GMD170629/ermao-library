import assert from 'node:assert/strict';
import test from 'node:test';
import emptyHighlight from '../../../../packages/reader-contracts/fixtures/reader-v5/reflowable-empty-highlight.json';
import pdfFixture from '../../../../packages/reader-contracts/fixtures/reader-v5/pdf.json';
import comicFixture from '../../../../packages/reader-contracts/fixtures/reader-v5/comic.json';
import audioFixture from '../../../../packages/reader-contracts/fixtures/reader-v5/audio.json';
import {
  parseReaderV5ProgressPut,
  parseReaderV5PositionReport,
  parseReaderV5ProgressSnapshot,
  positionReportsEqual
} from './v5-wire';
import { READER_V5_DB_NAME } from './v5-storage';

test('v5 preserves opaque Locator fields and independent presentation', () => {
  const position = parseReaderV5PositionReport(emptyHighlight.position);
  assert.ok(position);
  assert.equal(position.presentation.totalProgression, 0.99);
  assert.deepEqual(position.locator, emptyHighlight.position.locator);
  assert.strictEqual(position.locator, emptyHighlight.position.locator);
});

test('all cross-platform v5 position fixtures survive transport round trips unchanged', () => {
  const fixtures = [emptyHighlight, pdfFixture, comicFixture, audioFixture] as const;
  for (const fixture of fixtures) {
    const position = parseReaderV5PositionReport(fixture.position);
    assert.ok(position, fixture.clientId);
    const wire = JSON.parse(JSON.stringify({
      schemaVersion: fixture.schemaVersion,
      clientId: fixture.clientId,
      mutationId: fixture.mutationId,
      capturedAtEpochMillis: fixture.capturedAtEpochMillis,
      position
    })) as unknown;
    const reparsed = parseReaderV5ProgressPut(wire);
    assert.ok(reparsed, fixture.clientId);
    assert.deepEqual(reparsed.position, position, fixture.clientId);
    assert.deepEqual(reparsed.position.locator, fixture.position.locator, fixture.clientId);
  }
});

test('v4 snapshots are ignored by the v5 boundary and use a fresh local namespace', () => {
  assert.equal(parseReaderV5ProgressSnapshot({
    schemaVersion: 4,
    clientId: 'old-client',
    revision: 3,
    locator: { kind: 'reflowable', href: 'old.xhtml' },
    displayPercent: 12,
    receivedAtEpochMillis: 1
  }), null);
  assert.equal(READER_V5_DB_NAME, 'shuku-reader-v5');
});

test('position equality follows JSON object semantics, not insertion order', () => {
  const left = {
    locator: { href: 'chapter.xhtml', locations: { progression: 0.2, totalProgression: 0.2 } },
    presentation: {
      displayPercent: 20,
      totalProgression: 0.2,
      currentHref: 'chapter.xhtml',
      chapter: { href: 'chapter.xhtml', title: 'Chapter', index: 0 },
      page: null,
      playback: null
    }
  } as const;
  const right = {
    presentation: {
      playback: null,
      page: null,
      chapter: { index: 0, title: 'Chapter', href: 'chapter.xhtml' },
      currentHref: 'chapter.xhtml',
      totalProgression: 0.2,
      displayPercent: 20
    },
    locator: { locations: { totalProgression: 0.2, progression: 0.2 }, href: 'chapter.xhtml' }
  } as const;
  assert.equal(positionReportsEqual(left, right), true);
});

test('rejects non-JSON opaque Locator values before size or transport handling', () => {
  const base = emptyHighlight.position;
  const invalidValues: unknown[] = [undefined, () => true, Symbol('locator'), Number.NaN, Number.POSITIVE_INFINITY, new Date()];
  for (const invalid of invalidValues) {
    assert.equal(parseReaderV5PositionReport({
      ...base,
      locator: { ...base.locator, invalid }
    }), null);
  }
  class LocatorExtension { value = 1; }
  assert.equal(parseReaderV5PositionReport({
    ...base,
    locator: { ...base.locator, invalid: new LocatorExtension() }
  }), null);
  const cycle: Record<string, unknown> = {};
  cycle.self = cycle;
  assert.equal(parseReaderV5PositionReport({
    ...base,
    locator: { ...base.locator, cycle }
  }), null);
  const symbolKey = Symbol('key');
  const withSymbolKey = { ...base.locator, [symbolKey]: true };
  assert.equal(parseReaderV5PositionReport({ ...base, locator: withSymbolKey }), null);
});
