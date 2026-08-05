import { READER_SCHEMA_VERSION, type ReaderFontFamily, type ReaderPreferences, type ReaderTheme } from './types';

export const DEFAULT_READER_PREFERENCES: Readonly<ReaderPreferences> = Object.freeze({
  schemaVersion: READER_SCHEMA_VERSION,
  appearance: Object.freeze({ theme: 'warm', themeMode: 'manual' }),
  display: Object.freeze({ progressStyle: 'auto', showClock: false }),
  interaction: Object.freeze({
    tapZones: 'standard',
    swipePageTurn: true,
    keyboardPageTurn: true,
    volumeKeyPageTurn: false,
    keepScreenAwake: false
  }),
  epub: Object.freeze({
    fontSize: 18,
    lineHeight: 1.9,
    pageWidth: 1350,
    fontFamily: 'pingfang',
    fontWeight: 400,
    letterSpacing: 0,
    pageMargin: 'standard',
    spreadMode: 'single',
    pageTurnAnimation: 'slide',
    flow: 'paginated',
    typography: Object.freeze({
      paragraphIndent: 2,
      paragraphSpacing: 0,
      textAlign: 'publisher',
      preservePublisherStyles: false,
      allowPublisherColors: false,
      allowPublisherFonts: false
    }),
    optimization: Object.freeze({
      enabled: true,
      deduplicateIndent: true,
      indentUnindented: true
    })
  }),
  comic: Object.freeze({
    direction: 'ltr',
    mode: 'single',
    pageTurnAnimation: 'slide',
    imageFit: 'width',
    imageVariant: 'original',
    zoom: 1,
    flow: 'paged',
    coverSingle: false,
    pageGap: 0
  }),
  pdf: Object.freeze({
    zoom: 1,
    fit: 'page',
    flow: 'paged',
    rotation: 0,
    cropMargins: 'off'
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

function choice<T extends string | number>(value: unknown, choices: readonly T[], fallback: T): T {
  return (typeof value === 'string' || typeof value === 'number') && choices.includes(value as T) ? value as T : fallback;
}

function boolean(value: unknown, fallback: boolean) {
  return typeof value === 'boolean' ? value : fallback;
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
    display: { ...value.display },
    interaction: { ...value.interaction },
    epub: {
      ...value.epub,
      typography: { ...value.epub.typography },
      optimization: { ...value.epub.optimization }
    },
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
  const interaction = record(source.interaction);
  const display = record(source.display);
  const epub = record(source.epub);
  const epubTypography = record(epub.typography);
  const epubOptimization = record(epub.optimization);
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
      theme: choice<ReaderTheme>(appearance.theme ?? legacyTheme, ['day', 'warm', 'green', 'night', 'black'], fallback.appearance.theme),
      themeMode: choice(appearance.themeMode, ['manual', 'system'], fallback.appearance.themeMode)
    },
    display: {
      progressStyle: choice(display.progressStyle, ['auto', 'percent', 'position', 'remaining', 'hidden'], fallback.display.progressStyle),
      showClock: boolean(display.showClock, fallback.display.showClock)
    },
    interaction: {
      tapZones: choice(interaction.tapZones, ['standard', 'reversed', 'disabled'], fallback.interaction.tapZones),
      swipePageTurn: boolean(interaction.swipePageTurn, fallback.interaction.swipePageTurn),
      keyboardPageTurn: boolean(interaction.keyboardPageTurn, fallback.interaction.keyboardPageTurn),
      volumeKeyPageTurn: boolean(interaction.volumeKeyPageTurn, fallback.interaction.volumeKeyPageTurn),
      keepScreenAwake: boolean(interaction.keepScreenAwake, fallback.interaction.keepScreenAwake)
    },
    epub: {
      fontSize: clamp(epub.fontSize ?? source.fontSize, 14, 30, fallback.epub.fontSize),
      lineHeight: clamp(epub.lineHeight ?? source.lineHeight, 1.4, 2.4, fallback.epub.lineHeight, 1),
      pageWidth: clamp(epub.pageWidth ?? source.pageWidth, 600, 1350, fallback.epub.pageWidth),
      fontFamily: choice<ReaderFontFamily>(epub.fontFamily ?? source.fontFamily, ['pingfang', 'heiti', 'songti', 'yahei', 'kaiti'], fallback.epub.fontFamily),
      fontWeight: choice(epub.fontWeight, [400, 500, 700] as const, fallback.epub.fontWeight),
      letterSpacing: choice(epub.letterSpacing, [-0.02, 0, 0.04, 0.08] as const, fallback.epub.letterSpacing),
      pageMargin: choice(epub.pageMargin, ['narrow', 'standard', 'wide'], fallback.epub.pageMargin),
      spreadMode: choice(epub.spreadMode, ['auto', 'single', 'double'], fallback.epub.spreadMode),
      pageTurnAnimation: normalizeEpubPageTurnAnimation(epub.pageTurnAnimation ?? legacyPageTurnAnimation, fallback.epub.pageTurnAnimation),
      flow: choice(epub.flow, ['paginated', 'scrolled'], fallback.epub.flow),
      typography: {
        paragraphIndent: clamp(epubTypography.paragraphIndent, 0, 4, fallback.epub.typography.paragraphIndent, 1),
        paragraphSpacing: clamp(epubTypography.paragraphSpacing, 0, 1.5, fallback.epub.typography.paragraphSpacing, 1),
        textAlign: choice(epubTypography.textAlign, ['publisher', 'left', 'justify'], fallback.epub.typography.textAlign),
        preservePublisherStyles: boolean(epubTypography.preservePublisherStyles, fallback.epub.typography.preservePublisherStyles),
        allowPublisherColors: boolean(epubTypography.allowPublisherColors, fallback.epub.typography.allowPublisherColors),
        allowPublisherFonts: boolean(epubTypography.allowPublisherFonts, fallback.epub.typography.allowPublisherFonts)
      },
      optimization: {
        enabled: boolean(epubOptimization.enabled, fallback.epub.optimization.enabled),
        deduplicateIndent: boolean(epubOptimization.deduplicateIndent, fallback.epub.optimization.deduplicateIndent),
        indentUnindented: boolean(epubOptimization.indentUnindented, fallback.epub.optimization.indentUnindented)
      }
    },
    comic: {
      direction: choice(comic.direction ?? legacyComicDirection, ['ltr', 'rtl'], fallback.comic.direction),
      mode: choice(comic.mode ?? legacyComicMode, ['single', 'double'], fallback.comic.mode),
      pageTurnAnimation: choice(comic.pageTurnAnimation, ['slide', 'off'], fallback.comic.pageTurnAnimation),
      imageFit: choice(comic.imageFit ?? source.imageFit, ['width', 'height', 'contain', 'original'], fallback.comic.imageFit),
      imageVariant: choice(comic.imageVariant ?? source.imageVariant, ['original', 'data-saver'], fallback.comic.imageVariant),
      zoom: clamp(comic.zoom ?? source.zoom, 0.6, 2.4, fallback.comic.zoom, 1),
      flow: choice(comic.flow, ['paged', 'vertical'], fallback.comic.flow),
      coverSingle: boolean(comic.coverSingle, fallback.comic.coverSingle),
      pageGap: choice(comic.pageGap, [0, 8, 16, 24] as const, fallback.comic.pageGap)
    },
    pdf: {
      zoom: clamp(pdf.zoom ?? source.zoom, 0.6, 2.4, fallback.pdf.zoom, 1),
      fit: choice(pdf.fit, ['width', 'page'], fallback.pdf.fit),
      flow: choice(pdf.flow, ['paged', 'continuous'], fallback.pdf.flow),
      rotation: choice(pdf.rotation, [0, 90, 180, 270] as const, fallback.pdf.rotation),
      cropMargins: choice(pdf.cropMargins, ['off', 'auto'], fallback.pdf.cropMargins)
    }
  };
}

export function inheritReaderPreferences(serverDefault: unknown) {
  return normalizeReaderPreferences(serverDefault, DEFAULT_READER_PREFERENCES);
}
