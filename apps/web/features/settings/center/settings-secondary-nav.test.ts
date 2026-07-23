import assert from 'node:assert/strict';
import test from 'node:test';
import { isSettingsItemActive, settingsGroups, settingsItems } from './settings-secondary-nav';

test('settings navigation is grouped into reader, user, system, then about', () => {
  assert.deepEqual(settingsGroups.map((group) => group.label), ['阅读器', '用户设置', '系统设置', null]);
  assert.deepEqual(
    settingsGroups.find((group) => group.key === 'system')?.items.map((item) => item.label),
    ['用户管理', '书库来源和导入', '智能整理', '数据和系统', '系统日志']
  );
  assert.ok(settingsItems.some((item) => item.href === '/settings/about' && item.label === '关于'));
});

test('only the matching settings section is active', () => {
  assert.equal(isSettingsItemActive('/settings/about', '/settings'), false);
  assert.equal(isSettingsItemActive('/settings/about', '/settings/about'), true);
  assert.equal(isSettingsItemActive('/settings/about/details', '/settings/about'), true);
});
