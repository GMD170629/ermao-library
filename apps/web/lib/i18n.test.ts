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
    translateMessage('en-US', '创建于 {value0}', { value0: 'Example' }),
    'Created Example'
  );
  assert.equal(
    translateMessage('zh-CN', '查看《{value0}》，阅读进度 {value1}%', { value0: '示例', value1: 42 }),
    '查看《示例》，阅读进度 42%'
  );
  assert.equal(
    translateMessage('en-US', '查看《{value0}》，阅读进度 {value1}%', { value0: 'Example', value1: 42 }),
    'View Example, 42% read'
  );
  assert.equal(translateMessage('en-US', '创建于 Example'), 'Created Example');
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
  assert.equal(translateMessage('en-US', '已选 {value0} 本', { value0: 2 }), '2 books selected');
  assert.equal(translateMessage('zh-CN', '已选 {value0} 本', { value0: 1 }), '已选 1 本');
});

test('brand metadata has a deliberate English translation', () => {
  assert.equal(translateMessage('en-US', '二毛图书'), 'Ermao Books');
  assert.equal(
    translateMessage('en-US', '自托管私人图书馆与沉浸阅读应用'),
    'A self-hosted private library and immersive reading app'
  );
});

test('administrator API errors and audit events remain translated in both locales', () => {
  const messages: Record<string, string> = {
    '不能删除当前登录的管理员': 'The currently signed-in administrator cannot be deleted',
    '不能停用或降级当前登录的管理员': 'The currently signed-in administrator cannot be disabled or demoted',
    '仅管理员可以管理用户与权限': 'Only administrators can manage users and permissions',
    '确认邮箱不匹配': 'Confirmation email does not match',
    '系统必须至少保留一个有效管理员': 'The system must retain at least one active administrator',
    '用户不存在': 'User not found',
    '管理员创建了用户': 'An administrator created a user',
    '管理员更新了用户与权限': 'An administrator updated a user and permissions',
    '管理员永久删除了用户及其个人数据': 'An administrator permanently deleted a user and their personal data',
    '管理员重置了用户密码并撤销会话': 'An administrator reset a user password and revoked their sessions'
  };

  for (const [source, english] of Object.entries(messages)) {
    assert.equal(translateMessage('zh-CN', source), source);
    assert.equal(translateMessage('en-US', source), english);
  }
});
