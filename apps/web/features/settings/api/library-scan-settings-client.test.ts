import assert from 'node:assert/strict';
import test from 'node:test';

import { parseLibraryScanSettings } from './library-scan-settings-client';

test('parses valid library scan settings', () => {
  assert.deepEqual(
    parseLibraryScanSettings({ ok: true, data: { watchEnabled: true, intervalMinutes: 30 } }),
    { watchEnabled: true, intervalMinutes: 30 }
  );
});

test('rejects malformed or out-of-range library scan settings', () => {
  assert.throws(
    () => parseLibraryScanSettings({ ok: true, data: { watchEnabled: 'yes', intervalMinutes: 30 } }),
    /响应格式不正确/
  );
  assert.throws(
    () => parseLibraryScanSettings({ ok: true, data: { watchEnabled: true, intervalMinutes: 2 } }),
    /响应格式不正确/
  );
});
