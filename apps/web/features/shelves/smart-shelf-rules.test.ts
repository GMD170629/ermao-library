import assert from 'node:assert/strict';
import test from 'node:test';
import { summarizeSmartShelfRules } from './smart-shelf-rules';

test('summarizes base and combined smart shelf rules for display', () => {
  assert.deepEqual(summarizeSmartShelfRules({
    search: '星际',
    statuses: ['READING'],
    mediaKinds: ['EBOOK', 'COMIC'],
    combinator: 'ANY',
    conditions: [
      { field: 'publishedYear', operator: 'between', value: ['2020', '2025'] },
      { field: 'hasCover', operator: 'is_true' }
    ]
  }), [
    { label: '搜索', value: '包含“星际”' },
    { label: '阅读状态', value: '进行中' },
    { label: '读物类型', value: '电子书、漫画' },
    { label: '出版年份', value: '介于 2020 至 2025' },
    { label: '有封面', value: '是' }
  ]);
});

test('returns an empty list when a smart shelf includes all visible books', () => {
  assert.deepEqual(summarizeSmartShelfRules({ combinator: 'ALL', conditions: [] }), []);
});
