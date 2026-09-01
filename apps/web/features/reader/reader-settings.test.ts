import {
  DEFAULT_READER_PREFERENCES,
  READER_SETTINGS_CATALOG,
  changeReaderSetting,
  normalizeReaderPreferences,
  readerSettingAvailability,
  readerSettingValue
} from '@shuku/reader-core';
import assert from 'node:assert/strict';
import test from 'node:test';

test('settings edits preserve non-preset values and reset every format', () => {
  const preferences = normalizeReaderPreferences({ epub: { fontSize: 20, lineHeight: 1.85, letterSpacing: 0.03 }, comic: { zoom: 1.7 }, pdf: { rotation: 90 } });
  assert.equal(readerSettingValue(preferences, 'quickFontSize'), '20');
  assert.equal(readerSettingValue(preferences, 'lineHeight'), '1.85');
  const edited = changeReaderSetting(preferences, 'fontWeight', '700');
  assert.equal(edited.epub.lineHeight, 1.85);
  assert.equal(edited.epub.letterSpacing, 0.03);
  assert.deepEqual(changeReaderSetting(edited, 'reset', ''), DEFAULT_READER_PREFERENCES);
});

test('text layout exposes independent LTR RTL and horizontal vertical choices', () => {
  const readingProgression = READER_SETTINGS_CATALOG.settings.find((setting) => setting.id === 'textReadingProgression');
  const writingMode = READER_SETTINGS_CATALOG.settings.find((setting) => setting.id === 'textWritingMode');
  assert.equal(readingProgression?.section, 'textLayoutAdvanced');
  assert.equal(writingMode?.section, 'textLayoutAdvanced');
  assert.equal(readerSettingValue(DEFAULT_READER_PREFERENCES, 'textReadingProgression'), 'ltr');
  assert.equal(readerSettingValue(DEFAULT_READER_PREFERENCES, 'textWritingMode'), 'horizontal');
  const verticalRtl = changeReaderSetting(
    changeReaderSetting(DEFAULT_READER_PREFERENCES, 'textReadingProgression', 'rtl'),
    'textWritingMode',
    'vertical'
  );
  assert.equal(verticalRtl.epub.readingProgression, 'rtl');
  assert.equal(verticalRtl.epub.writingMode, 'vertical');
});

test('settings availability produces stable contextual results', () => {
  const supportedControls = new Set(READER_SETTINGS_CATALOG.settings.flatMap((setting) => setting.control ? [setting.control] : []));
  const context = {
    morphology: 'reflowable' as const,
    ready: true,
    supportedControls,
    wideViewport: true,
    wakeLockSupported: true,
    canZoom: true,
    preferences: DEFAULT_READER_PREFERENCES
  };
  assert.equal(readerSettingAvailability('textSpread', context).availability, 'available');
  const vertical = normalizeReaderPreferences({ epub: { writingMode: 'vertical', flow: 'paginated', spreadMode: 'double' } });
  assert.deepEqual(readerSettingAvailability('textFlow', { ...context, preferences: vertical }), {
    availability: 'temporarilyUnavailable', reason: 'verticalWritingMode'
  });
  assert.deepEqual(readerSettingAvailability('textSpread', { ...context, preferences: vertical }), {
    availability: 'temporarilyUnavailable', reason: 'verticalWritingMode'
  });
  assert.deepEqual(readerSettingAvailability('textPageWidth', { ...context, wideViewport: false }), {
    availability: 'temporarilyUnavailable', reason: 'narrowViewport'
  });
  assert.equal(readerSettingAvailability('comicSpread', context).availability, 'notApplicable');
  supportedControls.delete('VolumeKeys');
  assert.deepEqual(readerSettingAvailability('volumeKeyPageTurn', context), {
    availability: 'notImplemented', reason: 'notImplemented'
  });
});
