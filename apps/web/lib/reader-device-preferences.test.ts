import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_READER_PREFERENCES, normalizeReaderPreferences } from '@shuku/reader-core';
import { readDeviceReaderPreferences, writeDeviceReaderPreferences, clearDeviceReaderPreferences, READER_DEVICE_PREFERENCES_KEY } from './reader-device-preferences';
import { userDevicePreferenceKey } from './user-preferences';

test('device storage ignores non-V6 snapshots without rewriting them', () => {
  const records = new Map<string, string>();
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  let writes = 0;
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    localStorage: {
      getItem: (key: string) => records.get(key) ?? null,
      setItem: () => { writes += 1; },
      removeItem: () => undefined
    }
  } });
  try {
    const key = userDevicePreferenceKey(READER_DEVICE_PREFERENCES_KEY, 'alice');
    for (const snapshot of [{ epub: { fontSize: 24 } }, { ...DEFAULT_READER_PREFERENCES, schemaVersion: 5 }]) {
      const encoded = JSON.stringify(snapshot);
      records.set(key, encoded);
      assert.deepEqual(readDeviceReaderPreferences('alice', {}), DEFAULT_READER_PREFERENCES);
      assert.equal(records.get(key), encoded);
    }
    assert.equal(writes, 0);
  } finally {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});

test('local preferences and global-format reset are account-isolated and make no network requests', () => {
  const records = new Map<string, string>();
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const originalFetch = globalThis.fetch;
  let writes = 0;
  const events: Event[] = [];
  const windowPort = {
    localStorage: {
      getItem: (key: string) => records.get(key) ?? null,
      setItem: (key: string, value: string) => { writes += 1; records.set(key, value); },
      removeItem: (key: string) => records.delete(key)
    },
    dispatchEvent: (event: Event) => { events.push(event); return true; }
  };
  Object.defineProperty(globalThis, 'window', { configurable: true, value: windowPort });
  globalThis.fetch = () => { throw new Error('Reader preferences must never synchronize'); };
  try {
    const key = userDevicePreferenceKey(READER_DEVICE_PREFERENCES_KEY, 'alice');
    records.set(key, JSON.stringify(DEFAULT_READER_PREFERENCES));
    records.set('download-record', 'original-book');
    records.set('progress-record', 'exact-location-v4');
    assert.deepEqual(readDeviceReaderPreferences('alice', {}), DEFAULT_READER_PREFERENCES);
    assert.equal(writes, 0);
    const customized = normalizeReaderPreferences({ epub: { fontSize: 24 }, comic: { zoom: 1.7 }, pdf: { rotation: 90 } });
    writeDeviceReaderPreferences('bob', customized);
    writeDeviceReaderPreferences('alice', customized);
    clearDeviceReaderPreferences('alice');
    assert.deepEqual(readDeviceReaderPreferences('alice', {}), DEFAULT_READER_PREFERENCES);
    assert.deepEqual(readDeviceReaderPreferences('bob', {}), customized);
    assert.equal(records.get('download-record'), 'original-book');
    assert.equal(records.get('progress-record'), 'exact-location-v4');
    records.set(key, '{invalid');
    const writesBeforeFailure = writes;
    readDeviceReaderPreferences('alice', {});
    assert.equal(records.get(key), '{invalid');
    assert.equal(writes, writesBeforeFailure);
    assert.equal(events.length, 3);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});
