import type { IEpubPreferences, TextAlignment } from '@readium/navigator';
import type { ReaderPreferences } from '@shuku/reader-core';
import { readerThemeSurfaces } from '../../reader-theme';
import {
  applyEpubSmartTypography,
  epubPageWidth,
  resolveEpubViewportLayout
} from './epub-theme';
import { fallbackEpubFont, type EpubFontResolution } from './epub-font';

const BASE_EPUB_FONT_SIZE = 18;
const READIUM_PRESENTATION_STYLE = 'data-shuku-readium-presentation';
// Readium publishes TextAlignment as a runtime string enum, but importing the
// package at test time also evaluates its browser-only navigator entrypoint.
// These are the two exact public enum wire values supported by Reader Core.
const READIUM_TEXT_ALIGNMENT = {
  left: 'left' as TextAlignment,
  justify: 'justify' as TextAlignment
} as const;

export type ReadiumViewportPresentation = Readonly<{
  columnCount: 1 | 2;
  constraint: number;
  compact: boolean;
  pageGutter: number;
}>;

/**
 * Readium Web currently exposes pagination and native touch swiping, but not
 * configurable continuous layout or swipe suppression. Keep the persisted
 * schema intact while presenting the effective values to this adapter.
 */
export function projectReadiumEffectivePreferences(
  preferences: ReaderPreferences
): ReaderPreferences {
  return {
    ...preferences,
    interaction: {
      ...preferences.interaction,
      swipePageTurn: true
    },
    epub: {
      ...preferences.epub,
      flow: 'paginated',
      // Readium's responsive auto spread can expose the unused companion
      // column of short front-matter resources as a turnable blank page.
      // Keep the stored wire value compatible, but require an explicit user
      // choice before enabling a two-page layout.
      spreadMode: preferences.epub.spreadMode === 'double' ? 'double' : 'single',
      typography: { ...preferences.epub.typography },
      optimization: { ...preferences.epub.optimization }
    },
    comic: { ...preferences.comic },
    pdf: { ...preferences.pdf },
    appearance: { ...preferences.appearance },
    display: { ...preferences.display }
  };
}

export function resolveReadiumViewportPresentation(
  preferences: ReaderPreferences,
  viewportWidth: number
): ReadiumViewportPresentation {
  const normalizedWidth = Number.isFinite(viewportWidth) && viewportWidth > 0
    ? Math.round(viewportWidth)
    : epubPageWidth(preferences);
  const pageWidth = epubPageWidth(preferences);
  const viewportLayout = resolveEpubViewportLayout(normalizedWidth);
  const columnCount = preferences.epub.spreadMode === 'double' ? 2 : 1;

  return {
    columnCount,
    constraint: Math.max(0, normalizedWidth - pageWidth),
    compact: viewportLayout.compact,
    pageGutter: viewportLayout.compact
      ? { narrow: 8, standard: 16, wide: 24 }[preferences.epub.pageMargin]
      : { narrow: 16, standard: 24, wide: 40 }[preferences.epub.pageMargin]
  };
}

export function createReadiumEpubPreferences(
  preferences: ReaderPreferences,
  viewportWidth: number,
  resolvedFont: EpubFontResolution = fallbackEpubFont(preferences.epub.fontFamily)
): IEpubPreferences {
  const effective = projectReadiumEffectivePreferences(preferences);
  const layout = resolveReadiumViewportPresentation(effective, viewportWidth);
  const colors = readerThemeSurfaces[effective.appearance.theme];
  const allowPublisherColors = effective.epub.typography.allowPublisherColors;
  const allowPublisherFonts = effective.epub.typography.allowPublisherFonts;
  const preservePublisherStyles = effective.epub.typography.preservePublisherStyles;

  return {
    backgroundColor: allowPublisherColors ? null : colors.background,
    textColor: allowPublisherColors ? null : colors.color,
    linkColor: allowPublisherColors ? null : colors.link,
    visitedColor: allowPublisherColors ? null : colors.link,
    selectionBackgroundColor: allowPublisherColors ? null : colors.accent,
    selectionTextColor: allowPublisherColors ? null : colors.background,
    fontFamily: allowPublisherFonts ? null : resolvedFont.stack,
    fontSize: effective.epub.fontSize / BASE_EPUB_FONT_SIZE,
    fontWeight: effective.epub.fontWeight,
    // Readium rejects negative values. A null here clears any preceding native
    // value while the residual stylesheet applies Shuku's negative option.
    letterSpacing: effective.epub.letterSpacing < 0
      ? null
      : effective.epub.letterSpacing,
    lineHeight: preservePublisherStyles ? null : effective.epub.lineHeight,
    pageGutter: layout.pageGutter,
    paragraphIndent: effective.epub.typography.paragraphIndent,
    paragraphSpacing: effective.epub.typography.paragraphSpacing,
    textAlign: effective.epub.typography.textAlign === 'publisher'
      ? null
      : effective.epub.typography.textAlign === 'justify'
        ? READIUM_TEXT_ALIGNMENT.justify
        : READIUM_TEXT_ALIGNMENT.left,
    // Shuku's page-width control is the page measure itself. Readium's
    // built-in maximal line length would otherwise shrink a requested 1350px
    // page to its typography heuristic (about 1050px for the default font).
    maximalLineLength: null,
    minimalLineLength: null,
    // Single/double is always explicit. Legacy auto preferences are projected
    // to single before reaching this mapper.
    columnCount: layout.columnCount,
    constraint: layout.constraint,
    scroll: false
  };
}

/**
 * Small, late stylesheet for author !important declarations and presentation
 * values which Readium's public preference object cannot represent.
 */
export function createReadiumResidualStyle(
  preferences: ReaderPreferences,
  resolvedFont: EpubFontResolution = fallbackEpubFont(preferences.epub.fontFamily)
): string {
  const effective = projectReadiumEffectivePreferences(preferences);
  const colors = readerThemeSurfaces[effective.appearance.theme];
  const protectedBody = 'body:is(#shuku-readium-guard#shuku-readium-guard#shuku-readium-guard, *)';
  const fontFace = resolvedFont.embedded
    ? `@font-face { font-family: "${resolvedFont.embedded.family}"; src: url("${resolvedFont.embedded.url}") format("woff2"); font-display: swap; font-style: normal; font-weight: 400; }`
    : '';
  const colorOverride = effective.epub.typography.allowPublisherColors
    ? ''
    : `
      html, ${protectedBody} { background: ${colors.background} !important; color: ${colors.color} !important; }
      ${protectedBody} * { background-color: transparent !important; color: inherit !important; }
      ${protectedBody} a, ${protectedBody} a * { color: ${colors.link} !important; }
    `;
  const fontOverride = effective.epub.typography.allowPublisherFonts
    ? ''
    : `${protectedBody}, ${protectedBody} * { font-family: ${resolvedFont.stack} !important; }`;
  const lineHeightOverride = effective.epub.typography.preservePublisherStyles
    ? ''
    : `${protectedBody} { line-height: ${effective.epub.lineHeight} !important; } ${protectedBody} * { line-height: inherit !important; }`;
  const negativeLetterSpacing = effective.epub.letterSpacing < 0
    ? `${protectedBody}, ${protectedBody} * { letter-spacing: ${effective.epub.letterSpacing}em !important; }`
    : '';
  const paragraphAlignment = effective.epub.typography.textAlign === 'publisher'
    ? ''
    : `text-align: ${effective.epub.typography.textAlign} !important;`;
  return `
    ${fontFace}
    :root { color-scheme: ${colors.colorScheme} !important; }
    ${colorOverride}
    ${fontOverride}
    ${lineHeightOverride}
    ${negativeLetterSpacing}
    [data-shuku-smart-paragraph="true"] {
      ${paragraphAlignment}
      margin-block-start: ${effective.epub.typography.paragraphSpacing}em !important;
      margin-block-end: ${effective.epub.typography.paragraphSpacing}em !important;
    }
    .shuku-smart-deduplicate-indent { text-indent: 0 !important; }
    .shuku-smart-auto-indent { text-indent: ${effective.epub.typography.paragraphIndent}em !important; }
  `.trim();
}

export function applyReadiumDocumentPresentation(
  document: Document,
  preferences: ReaderPreferences,
  resolvedFont?: EpubFontResolution
) {
  const head = document.head ?? document.querySelector('head');
  if (!head) return;
  let style = head.querySelector<HTMLStyleElement>(`style[${READIUM_PRESENTATION_STYLE}]`);
  if (!style) {
    const namespace = document.documentElement?.namespaceURI;
    style = namespace
      ? document.createElementNS(namespace, 'style') as HTMLStyleElement
      : document.createElement('style');
    style.setAttribute(READIUM_PRESENTATION_STYLE, 'v1');
    head.append(style);
  }
  style.textContent = createReadiumResidualStyle(
    preferences,
    resolvedFont
  );
  applyEpubSmartTypography(document, projectReadiumEffectivePreferences(preferences));
}
