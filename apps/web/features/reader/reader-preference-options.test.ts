import { readFileSync } from 'node:fs';
import { READER_SETTINGS_CATALOG, normalizeReaderPreferences, readerSettingValue, changeReaderSetting, DEFAULT_READER_PREFERENCES } from '@shuku/reader-core';
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  READER_COMIC_DIRECTION_OPTIONS,
  READER_COMIC_IMAGE_FIT_OPTIONS,
  READER_FONT_SIZE_OPTIONS,
  READER_LINE_HEIGHT_OPTIONS,
  READER_PAGE_TURN_ANIMATION_OPTIONS
} from './reader-preference-options';

test('reader settings expose semantic display options instead of raw measurements', () => {
  assert.deepEqual(READER_FONT_SIZE_OPTIONS, [
    { value: '16', label: '小' },
    { value: '18', label: '中' },
    { value: '22', label: '大' }
  ]);
  assert.deepEqual(READER_LINE_HEIGHT_OPTIONS, [
    { value: '1.6', label: '小' },
    { value: '1.9', label: '中' },
    { value: '2.2', label: '大' }
  ]);
  assert.deepEqual(READER_PAGE_TURN_ANIMATION_OPTIONS.map(({ label }) => label), ['平移', '关闭']);
  assert.deepEqual(READER_COMIC_IMAGE_FIT_OPTIONS.map(({ label }) => label), ['宽度', '高度', '完整', '原始']);
  assert.deepEqual(READER_COMIC_DIRECTION_OPTIONS.map(({ label }) => label), ['左至右', '右至左']);
});

test('catalog edits preserve non-preset values and reset every format', () => {
  const preferences = normalizeReaderPreferences({ epub: { fontSize: 20, lineHeight: 1.85, letterSpacing: 0.03 }, comic: { zoom: 1.7 }, pdf: { rotation: 90 } });
  assert.equal(readerSettingValue(preferences, 'quickFontSize'), '20');
  assert.equal(readerSettingValue(preferences, 'lineHeight'), '1.85');
  const edited = changeReaderSetting(preferences, 'fontWeight', '700');
  assert.equal(edited.epub.lineHeight, 1.85);
  assert.equal(edited.epub.letterSpacing, 0.03);
  assert.deepEqual(changeReaderSetting(edited, 'reset', ''), DEFAULT_READER_PREFERENCES);
});

test('catalog and generated clients have one ordered bilingual settings contract', () => {
  assert.deepEqual(READER_SETTINGS_CATALOG, JSON.parse(readFileSync(new URL('../../../../packages/reader-contracts/reader-settings.json', import.meta.url), 'utf8')));
  assert.equal(READER_SETTINGS_CATALOG.settings.find((setting) => setting.id === 'preservePublisherStyles')?.section, 'paragraph');
  for (const setting of READER_SETTINGS_CATALOG.settings) {
    assert.ok(setting.label['zh-CN']);
    assert.ok(setting.label['en-US']);
    assert.doesNotMatch(setting.label['en-US'], /[\u3400-\u9fff]/);
  }
});
