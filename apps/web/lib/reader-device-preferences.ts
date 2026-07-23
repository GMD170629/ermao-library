import {
  inheritReaderPreferences,
  normalizeReaderPreferences,
  type ReaderPreferences
} from '@shuku/reader-core';
import { userDevicePreferenceKey } from './user-preferences';

export const READER_DEVICE_PREFERENCES_KEY = 'shuku:reader:device-defaults:v1';

export function readDeviceReaderPreferences(userId: string, fallback: unknown): ReaderPreferences {
  const inherited = inheritReaderPreferences(fallback);
  if (typeof window === 'undefined' || !userId) return inherited;
  try {
    const stored = window.localStorage.getItem(userDevicePreferenceKey(READER_DEVICE_PREFERENCES_KEY, userId));
    return stored ? normalizeReaderPreferences(JSON.parse(stored), inherited) : inherited;
  } catch {
    return inherited;
  }
}

export function writeDeviceReaderPreferences(userId: string, preferences: ReaderPreferences) {
  if (typeof window === 'undefined' || !userId) return;
  const normalized = normalizeReaderPreferences(preferences);
  window.localStorage.setItem(
    userDevicePreferenceKey(READER_DEVICE_PREFERENCES_KEY, userId),
    JSON.stringify(normalized)
  );
  window.dispatchEvent(new CustomEvent('shuku:reader-device-preferences-changed', {
    detail: { userId, preferences: normalized }
  }));
}

export function clearDeviceReaderPreferences(userId: string) {
  if (typeof window === 'undefined' || !userId) return;
  window.localStorage.removeItem(userDevicePreferenceKey(READER_DEVICE_PREFERENCES_KEY, userId));
  window.dispatchEvent(new CustomEvent('shuku:reader-device-preferences-changed', {
    detail: { userId, preferences: null }
  }));
}
