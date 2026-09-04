import assert from 'node:assert/strict';
import test from 'node:test';
import audioFixture from '../../../../packages/reader-contracts/fixtures/reader-v5/audio.json';
import comicFixture from '../../../../packages/reader-contracts/fixtures/reader-v5/comic.json';
import pdfFixture from '../../../../packages/reader-contracts/fixtures/reader-v5/pdf.json';
import reflowableFixture from '../../../../packages/reader-contracts/fixtures/reader-v5/reflowable-empty-highlight.json';
import {
  parseStandardReaderLocator,
  standardLocatorPosition,
  standardLocatorProgression,
  standardLocatorTimeSeconds
} from './v5-locator';
import { parseReaderV5PositionReport } from './v5-wire';

test('adapter-owned standard Locator views accept every v5 cross-platform fixture', () => {
  const cases = [
    { fixture: reflowableFixture, position: 190, progression: 1, time: null },
    { fixture: pdfFixture, position: 190, progression: 1, time: null },
    { fixture: comicFixture, position: 42, progression: 0, time: null },
    { fixture: audioFixture, position: 3, progression: 0.5, time: 120.5 }
  ] as const;

  for (const item of cases) {
    const report = parseReaderV5PositionReport(item.fixture.position);
    assert.ok(report, item.fixture.clientId);
    const locator = parseStandardReaderLocator(report.locator);
    assert.ok(locator, item.fixture.clientId);
    assert.equal(standardLocatorPosition(locator), item.position, item.fixture.clientId);
    assert.equal(standardLocatorProgression(locator), item.progression, item.fixture.clientId);
    assert.equal(standardLocatorTimeSeconds(locator), item.time, item.fixture.clientId);
    assert.deepEqual(report.locator, item.fixture.position.locator, item.fixture.clientId);
  }
});

test('adapter Locator interpretation is independent from presentation progression', () => {
  const report = parseReaderV5PositionReport({
    ...reflowableFixture.position,
    locator: {
      ...reflowableFixture.position.locator,
      locations: { ...reflowableFixture.position.locator.locations, position: 7, progression: 0.25 }
    },
    presentation: { ...reflowableFixture.position.presentation, displayPercent: 99, totalProgression: 0.99 }
  });
  assert.ok(report);
  const locator = parseStandardReaderLocator(report.locator);
  assert.ok(locator);
  assert.equal(standardLocatorPosition(locator), 7);
  assert.equal(standardLocatorProgression(locator), 0.25);
  assert.equal(report.presentation.displayPercent, 99);
});
