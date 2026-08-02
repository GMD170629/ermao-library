import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  LOCALE_OPTIONS,
  SUPPORTED_LOCALES,
  isAppLocale,
  normalizeLocale
} from '../i18n/config';
import enUS from '../i18n/messages/en-US.json';
import zhCN from '../i18n/messages/zh-CN.json';
import { translateMessage } from '../i18n/messages';

test('application locales are deliberately bounded', () => {
  assert.deepEqual(SUPPORTED_LOCALES, ['zh-CN', 'en-US']);
  assert.equal(DEFAULT_LOCALE, 'zh-CN');
  assert.equal(LOCALE_STORAGE_KEY, 'shuku.locale');
  assert.equal(isAppLocale('zh-CN'), true);
  assert.equal(isAppLocale('en-US'), true);
  assert.equal(isAppLocale('fr-FR'), false);
  assert.deepEqual(LOCALE_OPTIONS.map((option) => option.value), [...SUPPORTED_LOCALES]);
});

test('locale normalization accepts supported browser variants and rejects unrelated locales', () => {
  assert.equal(normalizeLocale('zh_hans'), 'zh-CN');
  assert.equal(normalizeLocale('zh-CN'), 'zh-CN');
  assert.equal(normalizeLocale('en'), 'en-US');
  assert.equal(normalizeLocale('en_US'), 'en-US');
  assert.equal(normalizeLocale('fr-FR'), 'zh-CN');
  assert.equal(normalizeLocale(null, 'en-US'), 'en-US');
});

test('Chinese and English catalogs have exactly the same keys', () => {
  assert.deepEqual(Object.keys(enUS).sort(), Object.keys(zhCN).sort());
  assert.equal(Object.entries(zhCN).every(([key, value]) => key === value), true);
  assert.equal(Object.values(enUS).some((value) => /[\u3400-\u9fff]/u.test(value)), false);
  const placeholders = (value: string) => Array.from(value.matchAll(/\{([a-zA-Z0-9_]+)\}/g), (match) => match[1]).sort();
  for (const key of Object.keys(zhCN)) {
    assert.deepEqual(placeholders(enUS[key as keyof typeof enUS]), placeholders(key), `placeholder mismatch for ${key}`);
  }
});

test('messages translate static text, interpolated text, and surrounding JSX whitespace', () => {
  assert.equal(translateMessage('zh-CN', '保存'), '保存');
  assert.equal(translateMessage('en-US', '保存'), 'Save');
  assert.equal(translateMessage('en-US', '  保存  '), '  Save  ');
  assert.equal(
    translateMessage('en-US', '创建下载任务：{value0}', { value0: 'Example' }),
    'Created download task: Example'
  );
  assert.equal(translateMessage('en-US', '创建下载任务：Example'), 'Created download task: Example');
});

test('nested application copy is translated before interpolation', () => {
  assert.equal(
    translateMessage('en-US', '填写{value0}', {
      value0: translateMessage('en-US', '书名')
    }),
    'Enter Book name'
  );
  assert.equal(
    translateMessage('en-US', '已启用 {value0} 条规则 · {value1}', {
      value0: 1,
      value1: translateMessage('en-US', '同时满足全部条件')
    }),
    '1 rule(s) enabled · All conditions'
  );
  assert.equal(translateMessage('en-US', '卷号 {value0}', { value0: 2 }), 'Volume 2');
  assert.equal(translateMessage('zh-CN', '卷号 {value0}', { value0: 1 }), '卷号 1');
});

test('brand metadata has a deliberate English translation', () => {
  assert.equal(translateMessage('en-US', '二毛图书'), 'Ermao Books');
  assert.equal(
    translateMessage('en-US', '自托管私人图书馆与沉浸阅读应用'),
    'A self-hosted private library and immersive reading app'
  );
});
