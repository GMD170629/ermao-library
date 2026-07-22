import { READER_SCHEMA_VERSION, type ReaderFontFamily, type ReaderPreferences, type ReaderTheme } from './types';

export const DEFAULT_READER_PREFERENCES: Readonly<ReaderPreferences> = Object.freeze({
  schemaVersion: READER_SCHEMA_VERSION,
  appearance: Object.freeze({ theme: 'warm' }),
  epub: Object.freeze({
    fontSize: 18,
    lineHeight: 1.9,
    pageWidth: 1350,
    fontFamily: 'pingfang',
    spreadMode: 'single',
    pageTurnAnimation: 'slide',
    flow: 'paginated'
  }),
  comic: Object.freeze({
    direction: 'ltr',
    mode: 'single',
    pageTurnAnimation: 'slide',
    imageFit: 'width',
    imageVariant: 'original',
    zoom: 1
  }),
  pdf: Object.freeze({
    zoom: 1,
    fit: 'width'
  })
});

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function finiteNumber(value: unknown, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function clamp(value: unknown, minimum: number, maximum: number, fallback: number, precision = 0) {
  const normalized = Math.max(minimum, Math.min(maximum, finiteNumber(value, fallback)));
  const scale = 10 ** precision;
  return Math.round(normalized * scale) / scale;
}

function choice<T extends string>(value: unknown, choices: readonly T[], fallback: T): T {
  return typeof value === 'string' && choices.includes(value as T) ? value as T : fallback;
}

function normalizeEpubPageTurnAnimation(value: unknown, fallback: 'slide' | 'off'): 'slide' | 'off' {
  // 'kindle' is a migration-only alias from the V2 preference schema.
  if (value === 'kindle') return 'slide';
  return choice(value, ['slide', 'off'], fallback);
}

function clonePreferences(value: Readonly<ReaderPreferences>): ReaderPreferences {
  return {
    schemaVersion: READER_SCHEMA_VERSION,
    appearance: { ...value.appearance },
    epub: { ...value.epub },
    comic: { ...value.comic },
    pdf: { ...value.pdf }
  };
}

/**
 * Normalizes V3, the V2 nested document, and the old flat settings object.
 * The returned value is always a complete snapshot; callers never merge partial
 * local settings at read time. Legacy 'kindle' values are canonicalized to 'slide'.
 */
export function normalizeReaderPreferences(value: unknown, base: Readonly<ReaderPreferences> = DEFAULT_READER_PREFERENCES): ReaderPreferences {
  const source = record(value);
  const appearance = record(source.appearance);
  const epub = record(source.epub);
  const comic = record(source.comic);
  const pdf = record(source.pdf);
  const fallback = clonePreferences(base);

  const legacyTheme = source.theme;
  const legacyPageTurnAnimation = source.ebookPageTurnAnimation;
  const legacyComicDirection = source.comicDirection;
  const legacyComicMode = source.comicMode;

  return {
    schemaVersion: READER_SCHEMA_VERSION,
    appearance: {
      theme: choice<ReaderTheme>(appearance.theme ?? legacyTheme, ['day', 'warm', 'night', 'black'], fallback.appearance.theme)
    },
    epub: {
      fontSize: clamp(epub.fontSize ?? source.fontSize, 14, 30, fallback.epub.fontSize),
      lineHeight: clamp(epub.lineHeight ?? source.lineHeight, 1.4, 2.4, fallback.epub.lineHeight, 1),
      pageWidth: clamp(epub.pageWidth ?? source.pageWidth, 600, 1350, fallback.epub.pageWidth),
      fontFamily: choice<ReaderFontFamily>(epub.fontFamily ?? source.fontFamily, ['pingfang', 'heiti', 'songti', 'yahei', 'kaiti'], fallback.epub.fontFamily),
      spreadMode: choice(epub.spreadMode, ['single', 'double'], fallback.epub.spreadMode),
      pageTurnAnimation: normalizeEpubPageTurnAnimation(epub.pageTurnAnimation ?? legacyPageTurnAnimation, fallback.epub.pageTurnAnimation),
      flow: choice(epub.flow, ['paginated', 'scrolled'], fallback.epub.flow)
    },
    comic: {
      direction: choice(comic.direction ?? legacyComicDirection, ['ltr', 'rtl'], fallback.comic.direction),
      mode: choice(comic.mode ?? legacyComicMode, ['single', 'double'], fallback.comic.mode),
      pageTurnAnimation: choice(comic.pageTurnAnimation, ['slide', 'off'], fallback.comic.pageTurnAnimation),
      imageFit: choice(comic.imageFit ?? source.imageFit, ['width', 'height', 'contain', 'original'], fallback.comic.imageFit),
      imageVariant: choice(comic.imageVariant ?? source.imageVariant, ['original', 'data-saver'], fallback.comic.imageVariant),
      zoom: clamp(comic.zoom ?? source.zoom, 0.6, 2.4, fallback.comic.zoom, 1)
    },
    pdf: {
      zoom: clamp(pdf.zoom ?? source.zoom, 0.6, 2.4, fallback.pdf.zoom, 1),
      fit: choice(pdf.fit, ['width', 'page'], fallback.pdf.fit)
    }
  };
}

export function inheritReaderPreferences(serverDefault: unknown) {
  return normalizeReaderPreferences(serverDefault, DEFAULT_READER_PREFERENCES);
}
