import { READER_PREFERENCES_VERSION, type ReaderFontFamily, type ReaderPreferences, type ReaderTheme } from './types';

export const DEFAULT_READER_PREFERENCES: Readonly<ReaderPreferences> = Object.freeze({
  schemaVersion: READER_PREFERENCES_VERSION,
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
    }),
    optimization: Object.freeze({
      enabled: true,
      deduplicateIndent: true,
      indentUnindented: true
    })
  }),
  comic: Object.freeze({
    direction: 'ltr',
    spreadMode: 'single',
    pageTurnAnimation: 'slide',
    imageFit: 'width',
    imageVariant: 'original',
    zoom: 1,
    pageWidth: 1350,
    flow: 'paginated',
    coverSingle: false,
    pageGap: 0
  }),
  pdf: Object.freeze({
    zoom: 1,
    pageWidth: 1350,
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

function clamp(value: unknown, minimum: number, maximum: number, fallback: number, precision?: number) {
  const normalized = Math.max(minimum, Math.min(maximum, finiteNumber(value, fallback)));
  if (precision === undefined) return normalized;
  const scale = 10 ** precision;
  return Math.round(normalized * scale) / scale;
}

function choice<T extends string | number>(value: unknown, choices: readonly T[], fallback: T): T {
  return (typeof value === 'string' || typeof value === 'number') && choices.includes(value as T) ? value as T : fallback;
}

function boolean(value: unknown, fallback: boolean) {
  return typeof value === 'boolean' ? value : fallback;
}

function readerFontFamily(value: unknown, fallback: ReaderFontFamily): ReaderFontFamily {
  if (value === 'heiti' || value === 'yahei') return 'pingfang';
  return choice<ReaderFontFamily>(value, ['pingfang', 'songti', 'kaiti'], fallback);
}

function assertOnlyKeys(value: Record<string, unknown>, allowed: readonly string[], section: string) {
  if (Object.keys(value).some((key) => !allowed.includes(key))) {
    throw new TypeError(`Unsupported reader preference fields in ${section}`);
  }
}

function normalizePageTurnAnimation(value: unknown, fallback: 'slide' | 'off'): 'slide' | 'off' {
  if (value === undefined) return fallback;
  if (value === 'slide' || value === 'off') return value;
  throw new TypeError('Unsupported EPUB page-turn animation');
}

function normalizeComicFlow(value: unknown, fallback: 'paginated' | 'scrolled'): 'paginated' | 'scrolled' {
  if (value === undefined) return fallback;
  if (value === 'paginated' || value === 'scrolled') return value;
  throw new TypeError('Unsupported comic reader flow');
}

function normalizePdfFlow(value: unknown): 'paged' {
  if (value === undefined || value === 'paged') return 'paged';
  throw new TypeError('Unsupported PDF reader flow');
}

function clonePreferences(value: Readonly<ReaderPreferences>): ReaderPreferences {
  return {
    schemaVersion: READER_PREFERENCES_VERSION,
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

/** Normalizes a partial current V5 preference snapshot into a complete value. */
export function normalizeReaderPreferences(value: unknown, base: Readonly<ReaderPreferences> = DEFAULT_READER_PREFERENCES): ReaderPreferences {
  const source = record(value);
  if (source.schemaVersion !== undefined && source.schemaVersion !== READER_PREFERENCES_VERSION) {
    throw new TypeError('Reader preferences must use schema version 5');
  }
  assertOnlyKeys(source, ['schemaVersion', 'appearance', 'display', 'interaction', 'epub', 'comic', 'pdf'], 'root');
  const appearance = record(source.appearance);
  const interaction = record(source.interaction);
  const display = record(source.display);
  const epub = record(source.epub);
  const epubTypography = record(epub.typography);
  const epubOptimization = record(epub.optimization);
  const comic = record(source.comic);
  const pdf = record(source.pdf);
  assertOnlyKeys(appearance, ['theme', 'themeMode'], 'appearance');
  assertOnlyKeys(display, ['progressStyle', 'showClock'], 'display');
  assertOnlyKeys(interaction, ['tapZones', 'swipePageTurn', 'keyboardPageTurn', 'volumeKeyPageTurn', 'keepScreenAwake'], 'interaction');
  assertOnlyKeys(epub, ['fontSize', 'lineHeight', 'pageWidth', 'fontFamily', 'fontWeight', 'letterSpacing', 'pageMargin', 'spreadMode', 'pageTurnAnimation', 'flow', 'typography', 'optimization'], 'epub');
  assertOnlyKeys(epubTypography, ['paragraphIndent', 'paragraphSpacing', 'textAlign', 'preservePublisherStyles'], 'epub.typography');
  assertOnlyKeys(epubOptimization, ['enabled', 'deduplicateIndent', 'indentUnindented'], 'epub.optimization');
  assertOnlyKeys(comic, ['direction', 'spreadMode', 'pageTurnAnimation', 'imageFit', 'imageVariant', 'zoom', 'pageWidth', 'flow', 'coverSingle', 'pageGap'], 'comic');
  assertOnlyKeys(pdf, ['zoom', 'pageWidth', 'fit', 'flow', 'rotation', 'cropMargins'], 'pdf');
  const fallback = clonePreferences(base);

  return {
    schemaVersion: READER_PREFERENCES_VERSION,
    appearance: {
      theme: choice<ReaderTheme>(appearance.theme, ['day', 'warm', 'green', 'night', 'black'], fallback.appearance.theme),
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
      fontSize: clamp(epub.fontSize, 14, 30, fallback.epub.fontSize, 0),
      lineHeight: clamp(epub.lineHeight, 1.4, 2.4, fallback.epub.lineHeight),
      pageWidth: clamp(epub.pageWidth, 600, 1350, fallback.epub.pageWidth, 0),
      fontFamily: readerFontFamily(epub.fontFamily, fallback.epub.fontFamily),
      fontWeight: choice(epub.fontWeight, [400, 500, 700] as const, fallback.epub.fontWeight),
      letterSpacing: clamp(epub.letterSpacing, -0.02, 0.08, fallback.epub.letterSpacing),
      pageMargin: choice(epub.pageMargin, ['narrow', 'standard', 'wide'], fallback.epub.pageMargin),
      spreadMode: choice(epub.spreadMode, ['auto', 'single', 'double'], fallback.epub.spreadMode),
      pageTurnAnimation: normalizePageTurnAnimation(epub.pageTurnAnimation, fallback.epub.pageTurnAnimation),
      flow: choice(epub.flow, ['paginated', 'scrolled'], fallback.epub.flow),
      typography: {
        paragraphIndent: clamp(epubTypography.paragraphIndent, 0, 4, fallback.epub.typography.paragraphIndent),
        paragraphSpacing: clamp(epubTypography.paragraphSpacing, 0, 1.5, fallback.epub.typography.paragraphSpacing),
        textAlign: choice(epubTypography.textAlign, ['publisher', 'left', 'justify'], fallback.epub.typography.textAlign),
        preservePublisherStyles: boolean(epubTypography.preservePublisherStyles, fallback.epub.typography.preservePublisherStyles),
      },
      optimization: {
        enabled: boolean(epubOptimization.enabled, fallback.epub.optimization.enabled),
        deduplicateIndent: boolean(epubOptimization.deduplicateIndent, fallback.epub.optimization.deduplicateIndent),
        indentUnindented: boolean(epubOptimization.indentUnindented, fallback.epub.optimization.indentUnindented)
      }
    },
    comic: {
      direction: choice(comic.direction, ['ltr', 'rtl'], fallback.comic.direction),
      spreadMode: choice(comic.spreadMode, ['single', 'double'], fallback.comic.spreadMode),
      pageTurnAnimation: choice(comic.pageTurnAnimation, ['slide', 'off'], fallback.comic.pageTurnAnimation),
      imageFit: choice(comic.imageFit, ['width', 'height', 'contain', 'original'], fallback.comic.imageFit),
      imageVariant: choice(comic.imageVariant, ['original', 'data-saver'], fallback.comic.imageVariant),
      zoom: clamp(comic.zoom, 0.6, 2.4, fallback.comic.zoom),
      pageWidth: clamp(comic.pageWidth, 600, 1350, fallback.comic.pageWidth, 0),
      flow: normalizeComicFlow(comic.flow, fallback.comic.flow),
      coverSingle: boolean(comic.coverSingle, fallback.comic.coverSingle),
      pageGap: choice(comic.pageGap, [0, 8, 16, 24] as const, fallback.comic.pageGap)
    },
    pdf: {
      zoom: clamp(pdf.zoom, 0.6, 2.4, fallback.pdf.zoom),
      pageWidth: clamp(pdf.pageWidth, 600, 1350, fallback.pdf.pageWidth, 0),
      fit: choice(pdf.fit, ['width', 'page'], fallback.pdf.fit),
      flow: normalizePdfFlow(pdf.flow),
      rotation: choice(pdf.rotation, [0, 90, 180, 270] as const, fallback.pdf.rotation),
      cropMargins: choice(pdf.cropMargins, ['off', 'auto'], fallback.pdf.cropMargins)
    }
  };
}

export function inheritReaderPreferences(serverDefault: unknown) {
  return normalizeReaderPreferences(serverDefault, DEFAULT_READER_PREFERENCES);
}
