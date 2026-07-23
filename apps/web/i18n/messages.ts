import enUS from './messages/en-US.json';
import zhCN from './messages/zh-CN.json';
import type { AppLocale } from './config';

export type MessageValues = Record<string, string | number | boolean | null | undefined>;
export type MessageCatalog = Record<string, string>;

const catalogs: Record<AppLocale, MessageCatalog> = {
  'zh-CN': zhCN,
  'en-US': enUS
};

const interpolationPattern = /\{([a-zA-Z0-9_]+)\}/g;
const dynamicPatterns = new Map<AppLocale, Array<{ pattern: RegExp; names: string[]; translation: string }>>();

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function compileDynamicPatterns(locale: AppLocale) {
  const existing = dynamicPatterns.get(locale);
  if (existing) return existing;

  const patterns = Object.entries(catalogs[locale]).flatMap(([source, translation]) => {
    const names = Array.from(source.matchAll(interpolationPattern), (match) => match[1]);
    if (names.length === 0) return [];

    let cursor = 0;
    let pattern = '^';
    for (const match of source.matchAll(interpolationPattern)) {
      const index = match.index ?? 0;
      pattern += escapeRegExp(source.slice(cursor, index));
      pattern += '(.+?)';
      cursor = index + match[0].length;
    }
    pattern += `${escapeRegExp(source.slice(cursor))}$`;
    return [{ pattern: new RegExp(pattern, 'u'), names, translation }];
  });
  patterns.sort((left, right) => right.pattern.source.length - left.pattern.source.length);
  dynamicPatterns.set(locale, patterns);
  return patterns;
}

function interpolate(message: string, values?: MessageValues) {
  if (!values) return message;
  return message.replace(interpolationPattern, (placeholder, name: string) => {
    const value = values[name];
    return value === undefined || value === null ? placeholder : String(value);
  });
}

export function translateMessage(locale: AppLocale, source: string, values?: MessageValues) {
  if (!source) return source;
  const direct = catalogs[locale][source];
  if (direct !== undefined) return interpolate(direct, values);
  if (locale === 'zh-CN') return interpolate(source, values);

  const whitespaceMatch = source.match(/^(\s*)([\s\S]*?)(\s*)$/u);
  const leadingWhitespace = whitespaceMatch?.[1] ?? '';
  const coreSource = whitespaceMatch?.[2] ?? source;
  const trailingWhitespace = whitespaceMatch?.[3] ?? '';
  const trimmedDirect = catalogs[locale][coreSource];
  if (trimmedDirect !== undefined) {
    return `${leadingWhitespace}${interpolate(trimmedDirect, values)}${trailingWhitespace}`;
  }

  for (const item of compileDynamicPatterns(locale)) {
    const match = item.pattern.exec(coreSource);
    if (!match) continue;
    const dynamicValues = Object.fromEntries(item.names.map((name, index) => [name, match[index + 1]]));
    return `${leadingWhitespace}${interpolate(item.translation, { ...dynamicValues, ...values })}${trailingWhitespace}`;
  }
  return interpolate(source, values);
}

export function hasMessage(locale: AppLocale, source: string) {
  return locale === 'zh-CN' || Object.prototype.hasOwnProperty.call(catalogs[locale], source);
}

export function messageKeys(locale: AppLocale) {
  return Object.keys(catalogs[locale]);
}
