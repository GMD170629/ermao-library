import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { validateMessageCatalogs } from './catalog-validation';
import { resolveSupportedLocale, translate } from './catalogs';

const REQUIRED_IOS_KEYS = [
  'CFBundleDisplayName',
  'NSCameraUsageDescription',
  'NSLocalNetworkUsageDescription',
] as const;

function isUnknownRecord(
  value: unknown,
): value is Readonly<Record<string, unknown>> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value)
  );
}

function readNativeMessages(
  locale: 'zh-CN' | 'en-US',
  platform: 'android' | 'ios',
): Readonly<Record<string, unknown>> {
  const filePath = fileURLToPath(
    new URL(`./native/${locale}.json`, import.meta.url),
  );
  const parsed: unknown = JSON.parse(readFileSync(filePath, 'utf8'));
  assert.ok(isUnknownRecord(parsed));
  const platformMessages = parsed[platform];
  assert.ok(isUnknownRecord(platformMessages));
  return platformMessages;
}

test('runtime catalogs have matching translated keys', () => {
  assert.deepEqual(validateMessageCatalogs(), []);
});

test('locale resolution supports Chinese variants and English fallback', () => {
  assert.equal(resolveSupportedLocale('zh-Hans-CN'), 'zh-CN');
  assert.equal(resolveSupportedLocale('en-GB'), 'en-US');
  assert.equal(resolveSupportedLocale(null), 'en-US');
});

test('translation replaces known values and preserves unknown placeholders', () => {
  assert.equal(
    translate('en-US', 'connection.profiles.deleteMessage', {
      server: 'https://library.example.com',
    }),
    'Remove https://library.example.com from this device? This does not delete server data.',
  );
  assert.equal(
    translate('en-US', 'connection.profiles.deleteMessage'),
    'Remove {server} from this device? This does not delete server data.',
  );
});

test('native system messages are complete for both locales', () => {
  for (const locale of ['zh-CN', 'en-US'] as const) {
    const iosMessages = readNativeMessages(locale, 'ios');
    const androidMessages = readNativeMessages(locale, 'android');
    for (const key of REQUIRED_IOS_KEYS) {
      assert.equal(typeof iosMessages[key], 'string');
      assert.notEqual(iosMessages[key], '');
    }
    assert.equal(typeof androidMessages.app_name, 'string');
    assert.notEqual(androidMessages.app_name, '');
  }
});

test('Expo locale config points each locale at one platform-nested catalog', () => {
  const appConfigPath = fileURLToPath(
    new URL('../../../app.json', import.meta.url),
  );
  const parsed: unknown = JSON.parse(readFileSync(appConfigPath, 'utf8'));
  assert.ok(isUnknownRecord(parsed));
  assert.ok(isUnknownRecord(parsed.expo));
  assert.deepEqual(parsed.expo.locales, {
    'zh-CN': './src/shared/i18n/native/zh-CN.json',
    'en-US': './src/shared/i18n/native/en-US.json',
  });
});
