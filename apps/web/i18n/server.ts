import { cookies } from 'next/headers';
import { DEFAULT_LOCALE, LOCALE_COOKIE_NAME, normalizeLocale, type AppLocale } from './config';
import { translateMessage, type MessageValues } from './messages';

export async function getRequestLocale(): Promise<AppLocale> {
  const cookieStore = await cookies();
  return normalizeLocale(cookieStore.get(LOCALE_COOKIE_NAME)?.value, DEFAULT_LOCALE);
}

export async function getServerTranslator(locale?: AppLocale) {
  const requestLocale = locale ?? await getRequestLocale();
  return (source: string, values?: MessageValues) => translateMessage(requestLocale, source, values);
}
