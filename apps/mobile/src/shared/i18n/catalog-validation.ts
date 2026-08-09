import {
  messageCatalogs,
  supportedLocales,
  type MessageCatalog,
  type MessageKey,
} from './catalogs';

const PLACEHOLDER_PATTERN = /\{[a-zA-Z][a-zA-Z0-9_]*\}/gu;
const HAN_CHARACTER_PATTERN = /\p{Script=Han}/u;

function placeholders(message: string): readonly string[] {
  return [...message.matchAll(PLACEHOLDER_PATTERN)]
    .map(([placeholder]) => placeholder)
    .sort();
}

function isMessageKey(
  key: string,
  catalog: MessageCatalog,
): key is MessageKey {
  return key in catalog;
}

export function validateMessageCatalogs(): readonly string[] {
  const issues: string[] = [];
  const sourceCatalog: MessageCatalog = messageCatalogs['zh-CN'];
  const sourceKeys = Object.keys(sourceCatalog).sort();

  for (const locale of supportedLocales) {
    const catalog = messageCatalogs[locale];
    const catalogKeys = Object.keys(catalog).sort();
    if (catalogKeys.join('\n') !== sourceKeys.join('\n')) {
      issues.push(`${locale}: catalog keys do not match zh-CN`);
    }

    for (const key of sourceKeys) {
      if (!isMessageKey(key, sourceCatalog)) {
        issues.push(`zh-CN:${key}: unknown source message key`);
        continue;
      }
      if (
        placeholders(catalog[key]).join('\n') !==
        placeholders(sourceCatalog[key]).join('\n')
      ) {
        issues.push(`${locale}:${key}: interpolation placeholders differ`);
      }
    }
  }

  for (const [key, message] of Object.entries(
    messageCatalogs['en-US'],
  )) {
    if (HAN_CHARACTER_PATTERN.test(message)) {
      issues.push(`en-US:${key}: contains untranslated Han characters`);
    }
  }

  return issues;
}
