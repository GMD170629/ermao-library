export const AUDIO_DEVICE_PREFERENCES_KEY = 'shuku:audio:preferences:v1';
export const AUDIO_PLAYBACK_RATE_OPTIONS = [0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3] as const;

export type AudioDevicePreferences = {
  playbackRate?: number;
  volume?: number;
};

export function audioDevicePreferenceKey(userId?: string, workId?: string) {
  if (userId && workId) {
    return `${AUDIO_DEVICE_PREFERENCES_KEY}:${encodeURIComponent(userId)}:${encodeURIComponent(workId)}`;
  }
  if (userId) return `${AUDIO_DEVICE_PREFERENCES_KEY}:${encodeURIComponent(userId)}`;
  return AUDIO_DEVICE_PREFERENCES_KEY;
}

export function readAudioDevicePreferences(userId?: string, workId?: string): AudioDevicePreferences {
  if (typeof window === 'undefined') return {};
  try {
    const keys = [
      userId && workId ? audioDevicePreferenceKey(userId, workId) : null,
      userId ? audioDevicePreferenceKey(userId) : null,
      AUDIO_DEVICE_PREFERENCES_KEY
    ].filter((key): key is string => Boolean(key));
    const stored = keys.map((key) => window.localStorage.getItem(key)).find((value) => value !== null);
    const value = JSON.parse(stored ?? '{}') as AudioDevicePreferences;
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

export function writeAudioDevicePreferences(
  preferences: AudioDevicePreferences,
  userId?: string,
  workId?: string
) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(audioDevicePreferenceKey(userId, workId), JSON.stringify(preferences));
  } catch {
    // Playback remains functional when local storage is unavailable.
  }
}

export function clearAudioDevicePreferences(userId: string) {
  if (typeof window === 'undefined' || !userId) return;
  window.localStorage.removeItem(audioDevicePreferenceKey(userId));
}
