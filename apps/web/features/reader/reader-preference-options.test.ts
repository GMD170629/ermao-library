import assert from 'node:assert/strict';
import test from 'node:test';
import {
  READER_COMIC_DIRECTION_OPTIONS,
  READER_COMIC_IMAGE_FIT_OPTIONS,
  READER_FONT_SIZE_OPTIONS,
  READER_LINE_HEIGHT_OPTIONS,
  READER_PAGE_TURN_ANIMATION_OPTIONS,
  READER_PAGE_WIDTH_OPTIONS,
  adjacentReaderOptionValue,
  closestReaderOptionValue
} from './reader-preference-options';

test('reader and device settings share semantic display options instead of raw measurements', () => {
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
  assert.deepEqual(READER_PAGE_WIDTH_OPTIONS.map(({ label }) => label), ['窄', '中', '宽']);
  assert.deepEqual(READER_PAGE_TURN_ANIMATION_OPTIONS.map(({ label }) => label), ['平移', '关闭']);
  assert.deepEqual(READER_COMIC_IMAGE_FIT_OPTIONS.map(({ label }) => label), ['宽度', '高度', '完整', '原始']);
  assert.deepEqual(READER_COMIC_DIRECTION_OPTIONS.map(({ label }) => label), ['左至右', '右至左']);
});

test('legacy numeric reader preferences resolve to the same nearest semantic option everywhere', () => {
  assert.equal(closestReaderOptionValue(20, READER_FONT_SIZE_OPTIONS), '18');
  assert.equal(closestReaderOptionValue(2.05, READER_LINE_HEIGHT_OPTIONS), '1.9');
  assert.equal(closestReaderOptionValue(1200, READER_PAGE_WIDTH_OPTIONS), '1050');
});

test('reader options move to an adjacent value without leaving the supported range', () => {
  assert.equal(adjacentReaderOptionValue(18, READER_FONT_SIZE_OPTIONS, -1), '16');
  assert.equal(adjacentReaderOptionValue(18, READER_FONT_SIZE_OPTIONS, 1), '22');
  assert.equal(adjacentReaderOptionValue(16, READER_FONT_SIZE_OPTIONS, -1), '16');
  assert.equal(adjacentReaderOptionValue(22, READER_FONT_SIZE_OPTIONS, 1), '22');
});
