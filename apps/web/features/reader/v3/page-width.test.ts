import assert from 'node:assert/strict';
import test from 'node:test';
import {
  effectiveReaderPageWidth,
  normalizeReaderPageWidth,
  readerPageWidthSliderMaximum
} from './page-width';

test('reader page width is normalized to the supported desktop range', () => {
  assert.equal(normalizeReaderPageWidth(420), 600);
  assert.equal(normalizeReaderPageWidth(980.4), 980);
  assert.equal(normalizeReaderPageWidth(1800), 1350);
});

test('mobile ignores the preference and desktop never exceeds the visible viewport', () => {
  assert.equal(effectiveReaderPageWidth(600, 390), 390);
  assert.equal(effectiveReaderPageWidth(1350, 900), 900);
  assert.equal(effectiveReaderPageWidth(760, 1200), 760);
  assert.equal(readerPageWidthSliderMaximum(880), 880);
  assert.equal(readerPageWidthSliderMaximum(1600), 1350);
});
