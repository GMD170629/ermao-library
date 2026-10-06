import assert from 'node:assert/strict';
import test from 'node:test';

import { parseLibraryScanSettings } from './library-scan-settings-client';

test('parses valid library scan settings', () => {
  for (const intervalMinutes of [0, 1440]) {
    assert.deepEqual(
      parseLibraryScanSettings({ ok: true, data: { watchEnabled: true, intervalMinutes } }),
      { watchEnabled: true, intervalMinutes }
    );
  }
});

test('rejects malformed or out-of-range library scan settings', () => {
  assert.throws(
    () => parseLibraryScanSettings({ ok: true, data: { watchEnabled: 'yes', intervalMinutes: 1440 } }),
    /响应格式不正确/
  );
  for (const intervalMinutes of [-1, 1, 2, 4, 5, 30, 60, 720, 1441, 30.5]) {
    assert.throws(
      () => parseLibraryScanSettings({ ok: true, data: { watchEnabled: true, intervalMinutes } }),
      /响应格式不正确/
    );
  }
});
