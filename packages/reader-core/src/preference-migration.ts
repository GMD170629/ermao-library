import { normalizeReaderPreferences, DEFAULT_READER_PREFERENCES } from './preferences';
import type { ReaderPreferences } from './types';

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('Invalid stored reader preferences');
  }
  return Object.fromEntries(Object.entries(value));
}

/** Storage-only migration. Web's former switch controlled line height, not publisher styles. */
export function migrateWebReaderPreferences(
  value: unknown,
  fallback: Readonly<ReaderPreferences> = DEFAULT_READER_PREFERENCES
): ReaderPreferences {
  const source = object(value);
  if (source.schemaVersion === 3 || source.schemaVersion === 4) {
    const epub = source.epub === undefined ? {} : object(source.epub);
    const typography = epub.typography === undefined ? {} : object(epub.typography);
    delete typography.allowPublisherColors;
    delete typography.allowPublisherFonts;
    typography.preservePublisherStyles = false;
    return normalizeReaderPreferences({
      ...source, schemaVersion: 5, epub: { ...epub, typography }
    }, fallback);
  }
  return normalizeReaderPreferences(source, fallback);
}
