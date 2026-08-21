import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_READER_PREFERENCES } from '@shuku/reader-core';
import { locationProgress, preferencesToReaderSettings, readerSettingsToPreferences } from './presentation';

test('round trips the complete book-scoped preference snapshot', () => {
  const settings = preferencesToReaderSettings(DEFAULT_READER_PREFERENCES);
  assert.deepEqual(readerSettingsToPreferences(settings), DEFAULT_READER_PREFERENCES);
});

test('projects discriminated locations into the existing visual progress model', () => {
  assert.deepEqual(locationProgress({ kind: 'pdf', pageIndex: 2, pageProgression: 0 }, 20, 11), {
    page: 3,
    total: 11,
    percent: 20,
    position: '3',
    label: '第 3 / 11 页'
  });
});

test('never presents the EPUB table of contents as chapters or physical pages', () => {
  assert.deepEqual(locationProgress({
    kind: 'epub',
    cfi: 'epubcfi(/6/482!/4/2/8:12)',
    href: 'all-chapters.xhtml#chapter-241',
    spineIndex: 4,
    progression: 0.31
  }, 31, 779), {
    page: 1,
    total: null,
    percent: 31,
    position: 'epubcfi(/6/482!/4/2/8:12)',
    label: '全书 31%'
  });
});

test('projects a reflowable location without inventing layout pages', () => {
  assert.deepEqual(locationProgress({
    kind: 'reflowable',
    format: 'txt',
    cfi: 'epubcfi(/6/8!/4/2:3)',
    progression: 0.72
  }, 72, 200), {
    page: 1,
    total: null,
    percent: 72,
    position: 'epubcfi(/6/8!/4/2:3)',
    label: '全书 72%'
  });
});
