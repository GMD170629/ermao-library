import assert from 'node:assert/strict';
import test from 'node:test';

import { decodeThemePreference } from './theme-preference';

test('accepts only the supported theme preferences', () => {
  assert.equal(decodeThemePreference('system'), 'system');
  assert.equal(decodeThemePreference('light'), 'light');
  assert.equal(decodeThemePreference('dark'), 'dark');
  assert.equal(decodeThemePreference('sepia'), 'system');
  assert.equal(decodeThemePreference({ preference: 'dark' }), 'system');
});
