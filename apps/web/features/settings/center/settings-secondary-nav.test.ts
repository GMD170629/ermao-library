import assert from 'node:assert/strict';
import test from 'node:test';
import { isSettingsItemActive, settingsItems } from './settings-secondary-nav';

test('settings navigation includes the about page', () => {
  assert.ok(settingsItems.some((item) => item.href === '/settings/about' && item.label === '关于'));
});

test('only the matching settings section is active', () => {
  assert.equal(isSettingsItemActive('/settings/about', '/settings'), false);
  assert.equal(isSettingsItemActive('/settings/about', '/settings/about'), true);
  assert.equal(isSettingsItemActive('/settings/about/details', '/settings/about'), true);
});
