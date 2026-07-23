export const SUPPORTED_LOCALES = ['zh-CN', 'en-US'] as const;

export type AppLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: AppLocale = 'zh-CN';
export const LOCALE_COOKIE_NAME = 'shuku_locale';
export const LOCALE_STORAGE_KEY = 'shuku.locale';
export const LOCALE_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

export const LOCALE_OPTIONS: ReadonlyArray<{ value: AppLocale; label: string }> = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'en-US', label: 'English (United States)' }
];

export function isAppLocale(value: unknown): value is AppLocale {
  return typeof value === 'string' && SUPPORTED_LOCALES.includes(value as AppLocale);
}

export function normalizeLocale(value: unknown, fallback: AppLocale = DEFAULT_LOCALE): AppLocale {
  if (isAppLocale(value)) return value;
  if (typeof value !== 'string') return fallback;

  const normalized = value.trim().toLowerCase().replace(/_/g, '-');
  if (normalized === 'zh' || normalized === 'zh-cn' || normalized === 'zh-hans' || normalized.startsWith('zh-hans-')) {
    return 'zh-CN';
  }
  if (normalized === 'en' || normalized === 'en-us' || normalized.startsWith('en-us-')) {
    return 'en-US';
  }
  return fallback;
}
