import assert from 'node:assert/strict';
import test from 'node:test';
import { summarizeSmartShelfRules } from './smart-shelf-rules';

test('summarizes base and combined smart shelf rules for display', () => {
  assert.deepEqual(summarizeSmartShelfRules({
    search: '星际',
    statuses: ['READING'],
    combinator: 'ANY',
    conditions: [
      { field: 'publishedYear', operator: 'between', value: ['2020', '2025'] },
      { field: 'hasCover', operator: 'is_true' }
    ]
  }), [
    { label: '搜索', value: '包含“星际”' },
    { label: '阅读状态', value: '进行中' },
    { label: '出版年份', value: '介于 2020 至 2025' },
    { label: '有封面', value: '是' }
  ]);
});

test('returns an empty list when a smart shelf includes all visible books', () => {
  assert.deepEqual(summarizeSmartShelfRules({ combinator: 'ALL', conditions: [] }), []);
});


test('translates rule labels and states without translating user content', () => {
  const translations: Record<string, string> = { '搜索': 'Search', '包含': 'Contains', '阅读状态': 'Reading status', '进行中': 'In progress', '作者': 'Author' };
  assert.deepEqual(summarizeSmartShelfRules({ search: '岛田庄司', statuses: ['READING'], authors: ['岛田庄司'] }, (text) => translations[text] ?? text), [
    { label: 'Search', value: 'Contains“岛田庄司”' },
    { label: 'Reading status', value: 'In progress' },
    { label: 'Author', value: '岛田庄司' }
  ]);
});
