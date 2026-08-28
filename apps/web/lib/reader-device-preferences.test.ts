import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_READER_PREFERENCES, migrateWebReaderPreferences, normalizeReaderPreferences, READER_SCHEMA_VERSION } from '@shuku/reader-core';
import { readDeviceReaderPreferences, writeDeviceReaderPreferences, clearDeviceReaderPreferences, READER_DEVICE_PREFERENCES_KEY } from './reader-device-preferences';
import { userDevicePreferenceKey } from './user-preferences';

test('Web migration drops legacy publisher switches, preserves custom values and leaves progress v4', () => {
  const legacy = {
    ...DEFAULT_READER_PREFERENCES, schemaVersion: 4,
    epub: { ...DEFAULT_READER_PREFERENCES.epub, lineHeight: 1.85, letterSpacing: 0.03,
      typography: { ...DEFAULT_READER_PREFERENCES.epub.typography, preservePublisherStyles: true, allowPublisherColors: true, allowPublisherFonts: true } }
  };
  const migrated = migrateWebReaderPreferences(legacy);
  assert.equal(migrated.schemaVersion, 5);
  assert.equal(READER_SCHEMA_VERSION, 4);
  assert.equal(migrated.epub.typography.preservePublisherStyles, false);
  assert.equal(migrated.epub.lineHeight, 1.85);
  assert.equal(migrated.epub.letterSpacing, 0.03);
  assert.deepEqual(Object.keys(migrated.epub.typography).sort(), ['paragraphIndent', 'paragraphSpacing', 'preservePublisherStyles', 'textAlign'].sort());
  assert.deepEqual(migrateWebReaderPreferences(migrated), migrated);
});

test('local preference migration and global-format reset are account-isolated and make no network requests', () => {
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
    const legacy = JSON.stringify({ ...DEFAULT_READER_PREFERENCES, schemaVersion: 4 });
    records.set(key, legacy);
    records.set('download-record', 'original-book');
    records.set('progress-record', 'exact-location-v4');
    const migrated = readDeviceReaderPreferences('alice', {});
    assert.equal(migrated.schemaVersion, 5);
    assert.equal(writes, 1);
    readDeviceReaderPreferences('alice', {});
    assert.equal(writes, 1);
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
