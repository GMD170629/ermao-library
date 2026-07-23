import { cookies } from 'next/headers';
import { DEFAULT_LOCALE, LOCALE_COOKIE_NAME, normalizeLocale, type AppLocale } from './config';
import { translateMessage, type MessageValues } from './messages';

export function getRequestLocale(): AppLocale {
  return normalizeLocale(cookies().get(LOCALE_COOKIE_NAME)?.value, DEFAULT_LOCALE);
}

export function getServerTranslator(locale = getRequestLocale()) {
  return (source: string, values?: MessageValues) => translateMessage(locale, source, values);
}

