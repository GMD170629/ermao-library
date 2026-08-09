import { useLocales } from 'expo-localization';
import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from 'react';

import {
  resolveSupportedLocale,
  translate,
  type MessageKey,
  type SupportedLocale,
  type TranslationValues,
} from './catalogs';

type I18nContextValue = Readonly<{
  locale: SupportedLocale;
  formatDateTime: (value: Date | number) => string;
  formatNumber: (value: number) => string;
  t: (key: MessageKey, values?: TranslationValues) => string;
}>;

const I18nContext = createContext<I18nContextValue | null>(null);

export type I18nProviderProps = Readonly<{
  children: ReactNode;
}>;

export function I18nProvider({
  children,
}: I18nProviderProps): ReactNode {
  const [preferredLocale] = useLocales();
  const locale = resolveSupportedLocale(preferredLocale.languageTag);
  const value = useMemo<I18nContextValue>(() => {
    const dateTimeFormat = new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
    const numberFormat = new Intl.NumberFormat(locale);

    return {
      locale,
      formatDateTime: (dateTime) => dateTimeFormat.format(dateTime),
      formatNumber: (number) => numberFormat.format(number),
      t: (key, values) => translate(locale, key, values),
    };
  }, [locale]);

  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  const value = useContext(I18nContext);
  if (value === null) {
    throw new Error('useI18n must be used within I18nProvider');
  }

  return value;
}
