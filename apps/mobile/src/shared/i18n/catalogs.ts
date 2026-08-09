import { enUSMessages } from './locales/en-US';
import { zhCNMessages } from './locales/zh-CN';

export const supportedLocales = ['zh-CN', 'en-US'] as const;

export type SupportedLocale = (typeof supportedLocales)[number];
export type MessageKey = keyof typeof zhCNMessages;
export type MessageCatalog = Readonly<Record<MessageKey, string>>;
export type TranslationValues = Readonly<
  Record<string, number | string>
>;

export const messageCatalogs: Readonly<
  Record<SupportedLocale, MessageCatalog>
> = {
  'zh-CN': zhCNMessages,
  'en-US': enUSMessages,
};

export function resolveSupportedLocale(
  languageTag: string | null,
): SupportedLocale {
  return languageTag?.toLowerCase().startsWith('zh') === true
    ? 'zh-CN'
    : 'en-US';
}

export function translate(
  locale: SupportedLocale,
  key: MessageKey,
  values?: TranslationValues,
): string {
  const message = messageCatalogs[locale][key];
  if (values === undefined) {
    return message;
  }
  return message.replace(
    /\{([a-zA-Z][a-zA-Z0-9_]*)\}/gu,
    (placeholder: string, valueKey: string) => {
      const value = values[valueKey];
      return value === undefined ? placeholder : String(value);
    },
  );
}
