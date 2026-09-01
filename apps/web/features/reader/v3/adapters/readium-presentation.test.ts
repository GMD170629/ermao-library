import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DEFAULT_READER_PREFERENCES,
  type ReaderPreferences,
  type ReaderTheme
} from '@shuku/reader-core';
import {
  createReadiumEpubPreferences,
  createReadiumResidualStyle,
  projectReadiumEffectivePreferences,
  resolveReadiumViewportPresentation
} from './readium-presentation';

const themeColors: Record<ReaderTheme, readonly [string, string, string]> = {
  day: ['#F7F7F4', '#1E293B', '#2563EB'],
  warm: ['#FDF6EA', '#2B2118', '#B45309'],
  green: ['#E8F0E3', '#203126', '#2F6B45'],
  night: ['#0F172A', '#E2E8F0', '#93C5FD'],
  black: ['#000000', '#F8FAFC', '#93C5FD']
};

function preferencesWith(
  epub: Partial<ReaderPreferences['epub']>,
  typography: Partial<ReaderPreferences['epub']['typography']> = {}
): ReaderPreferences {
  return {
    ...DEFAULT_READER_PREFERENCES,
    appearance: { ...DEFAULT_READER_PREFERENCES.appearance },
    interaction: { ...DEFAULT_READER_PREFERENCES.interaction },
    display: { ...DEFAULT_READER_PREFERENCES.display },
    epub: {
      ...DEFAULT_READER_PREFERENCES.epub,
      ...epub,
      typography: {
        ...DEFAULT_READER_PREFERENCES.epub.typography,
        ...typography
      },
      optimization: { ...DEFAULT_READER_PREFERENCES.epub.optimization }
    },
    comic: { ...DEFAULT_READER_PREFERENCES.comic },
    pdf: { ...DEFAULT_READER_PREFERENCES.pdf }
  };
}

test('Readium maps all five reader themes to native colors', () => {
  for (const theme of Object.keys(themeColors) as ReaderTheme[]) {
    const input = {
      ...DEFAULT_READER_PREFERENCES,
      appearance: { theme, themeMode: 'manual' as const }
    };
    const mapped = createReadiumEpubPreferences(input, 1200);
    assert.deepEqual(
      [mapped.backgroundColor, mapped.textColor, mapped.linkColor],
      themeColors[theme]
    );
  }
});

test('Readium maps every native typography preference and submits scrolling', () => {
  const input = preferencesWith({
    fontSize: 27,
    lineHeight: 2.2,
    pageWidth: 900,
    fontWeight: 700,
    letterSpacing: 0.08,
    pageMargin: 'wide',
    spreadMode: 'double',
    flow: 'scrolled'
  }, {
    paragraphIndent: 3,
    paragraphSpacing: 0.75,
    textAlign: 'justify'
  });
  const mapped = createReadiumEpubPreferences(input, 1200, {
    source: 'system',
    stack: '"Test Serif", serif'
  });

  assert.equal(mapped.fontSize, 1.5);
  assert.equal(mapped.lineHeight, 2.2);
  assert.equal(mapped.fontFamily, '"Test Serif", serif');
  assert.equal(mapped.fontWeight, 700);
  assert.equal(mapped.letterSpacing, 0.08);
  assert.equal(mapped.pageGutter, 40);
  assert.equal(mapped.paragraphIndent, 3);
  assert.equal(mapped.paragraphSpacing, 0.75);
  assert.equal(mapped.textAlign, 'justify');
  assert.equal(mapped.columnCount, 1);
  assert.equal(mapped.constraint, 300);
  assert.equal(mapped.maximalLineLength, null);
  assert.equal(mapped.minimalLineLength, null);
  assert.equal(mapped.scroll, true);
});

test('publisher styles release publisher-owned typography but keep reader colors and font size', () => {
  const regular = createReadiumEpubPreferences(preferencesWith({}, { textAlign: 'publisher' }), 900);
  const requested = createReadiumEpubPreferences(preferencesWith({}, { preservePublisherStyles: true, textAlign: 'publisher' }), 900);
  assert.equal(requested.backgroundColor, regular.backgroundColor);
  assert.equal(requested.fontSize, regular.fontSize);
  assert.equal(requested.fontFamily, null);
  assert.equal(requested.fontWeight, null);
  assert.equal(requested.lineHeight, null);
  assert.equal(requested.paragraphIndent, null);
  assert.equal(projectReadiumEffectivePreferences(preferencesWith({}, { preservePublisherStyles: true })).epub.typography.preservePublisherStyles, true);
});

test('negative letter spacing clears the native value and uses residual CSS', () => {
  const input = preferencesWith({ letterSpacing: -0.02 });
  const mapped = createReadiumEpubPreferences(input, 900);
  const residual = createReadiumResidualStyle(input);

  assert.equal(mapped.letterSpacing, null);
  assert.match(residual, /letter-spacing: -0\.02em !important/);
});

test('page width constrains the navigator and auto spread is delegated to Readium', () => {
  const narrowMeasure = preferencesWith({ pageWidth: 600, spreadMode: 'auto' });
  const wideMeasure = preferencesWith({ pageWidth: 1350, spreadMode: 'auto' });

  assert.deepEqual(resolveReadiumViewportPresentation(narrowMeasure, 1200), {
    columnCount: 1,
    constraint: 600,
    compact: false,
    pageGutter: 24
  });
  assert.deepEqual(resolveReadiumViewportPresentation(wideMeasure, 1200), {
    columnCount: 1,
    constraint: 0,
    compact: false,
    pageGutter: 24
  });
  assert.equal(resolveReadiumViewportPresentation(wideMeasure, 390).columnCount, 1);
  assert.equal(createReadiumEpubPreferences(narrowMeasure, 1200).columnCount, null);
  assert.equal(createReadiumEpubPreferences(wideMeasure, 1200).columnCount, null);
});

test('effective projection fixes reflowable swipe on without mutating the saved preference', () => {
  const input = preferencesWith({ flow: 'scrolled', spreadMode: 'auto' });
  input.interaction.swipePageTurn = false;
  const projected = projectReadiumEffectivePreferences(input);

  assert.equal(projected.interaction.swipePageTurn, true);
  assert.equal(input.epub.flow, 'scrolled');
  assert.equal(input.epub.spreadMode, 'auto');
  assert.equal(input.interaction.swipePageTurn, false);
});

test('effective projection preserves an explicit double-page choice', () => {
  const projected = projectReadiumEffectivePreferences(preferencesWith({ spreadMode: 'double' }));

  assert.equal(projected.epub.spreadMode, 'double');
  assert.equal(createReadiumEpubPreferences(projected, 1200).columnCount, 2);
});

test('vertical writing forces scrolling and one column without overwriting saved horizontal choices', () => {
  const stored = preferencesWith({ writingMode: 'horizontal', flow: 'paginated', spreadMode: 'double' });
  const vertical = preferencesWith({ ...stored.epub, writingMode: 'vertical' });

  assert.equal(createReadiumEpubPreferences(vertical, 1200).scroll, true);
  assert.equal(createReadiumEpubPreferences(vertical, 1200).columnCount, 1);
  assert.equal(stored.epub.flow, 'paginated');
  assert.equal(stored.epub.spreadMode, 'double');
  assert.equal(createReadiumEpubPreferences(stored, 1200).scroll, false);
  assert.equal(createReadiumEpubPreferences(stored, 1200).columnCount, 2);
});

test('residual style stays small and only overrides publisher-owned surfaces when required', () => {
  const strict = createReadiumResidualStyle(DEFAULT_READER_PREFERENCES, {
    source: 'embedded',
    stack: '"Shuku Test", serif',
    embedded: { family: 'Shuku Test', url: 'blob:shuku-font' }
  });
  const publisher = createReadiumResidualStyle(preferencesWith({}, {
    preservePublisherStyles: true
  }));

  assert.match(strict, /@font-face/);
  assert.match(strict, /blob:shuku-font/);
  assert.match(strict, /background: #FDF6EA !important/);
  assert.match(strict, /font-family: "Shuku Test", serif !important/);
  assert.doesNotMatch(strict, /padding-block/);
  assert.doesNotMatch(strict, /data-shuku-readium-media-only/);
  assert.match(publisher, /background: #FDF6EA !important/);
  assert.doesNotMatch(publisher, /font-family: .* !important/);
  assert.doesNotMatch(publisher, /line-height: .* !important/);
  assert.doesNotMatch(publisher, /data-shuku-smart-paragraph/);
});
