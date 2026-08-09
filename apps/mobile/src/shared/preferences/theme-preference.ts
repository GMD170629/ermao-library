export type ThemePreference = 'dark' | 'light' | 'system';

export interface ThemePreferenceStore {
  load(): ThemePreference;
  save(preference: ThemePreference): Promise<void>;
}

export function decodeThemePreference(value: unknown): ThemePreference {
  return value === 'dark' || value === 'light' || value === 'system'
    ? value
    : 'system';
}
