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

/** Projects only the interaction values which the Web adapter cannot control. */
export function projectReadiumEffectivePreferences(
  preferences: ReaderPreferences
): ReaderPreferences {
  return {
    ...preferences,
    interaction: {
      ...preferences.interaction,
      swipePageTurn: true
    }
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
  const columnCount = preferences.epub.writingMode === 'horizontal'
    && preferences.epub.flow === 'paginated'
    && preferences.epub.spreadMode === 'double' ? 2 : 1;

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
  const publisherStyles = effective.epub.typography.preservePublisherStyles;

  return {
    backgroundColor: colors.background,
    textColor: colors.color,
    linkColor: colors.link,
    visitedColor: colors.link,
    selectionBackgroundColor: colors.accent,
    selectionTextColor: colors.background,
    fontFamily: publisherStyles ? null : resolvedFont.stack,
    fontSize: effective.epub.fontSize / BASE_EPUB_FONT_SIZE,
    fontWeight: publisherStyles ? null : effective.epub.fontWeight,
    // Readium rejects negative values. A null here clears any preceding native
    // value while the residual stylesheet applies Shuku's negative option.
    letterSpacing: publisherStyles || effective.epub.letterSpacing < 0
      ? null
      : effective.epub.letterSpacing,
    lineHeight: publisherStyles ? null : effective.epub.lineHeight,
    pageGutter: layout.pageGutter,
    paragraphIndent: publisherStyles ? null : effective.epub.typography.paragraphIndent,
    paragraphSpacing: publisherStyles ? null : effective.epub.typography.paragraphSpacing,
    textAlign: publisherStyles || effective.epub.typography.textAlign === 'publisher'
      ? null
      : effective.epub.typography.textAlign === 'justify'
        ? READIUM_TEXT_ALIGNMENT.justify
        : READIUM_TEXT_ALIGNMENT.left,
    // Shuku's page-width control is the page measure itself. Readium's
    // built-in maximal line length would otherwise shrink a requested 1350px
    // page to its typography heuristic (about 1050px for the default font).
    maximalLineLength: null,
    minimalLineLength: null,
    columnCount: effective.epub.spreadMode === 'auto' ? null : layout.columnCount,
    constraint: layout.constraint,
    scroll: effective.epub.writingMode === 'vertical' || effective.epub.flow === 'scrolled'
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
  const publisherStyles = effective.epub.typography.preservePublisherStyles;
  const protectedBody = 'body:is(#shuku-readium-guard#shuku-readium-guard#shuku-readium-guard, *)';
  const fontFace = !publisherStyles && resolvedFont.embedded
    ? `@font-face { font-family: "${resolvedFont.embedded.family}"; src: url("${resolvedFont.embedded.url}") format("woff2"); font-display: swap; font-style: normal; font-weight: 400; }`
    : '';
  const colorOverride = `
      html, ${protectedBody} { background: ${colors.background} !important; color: ${colors.color} !important; }
      ${protectedBody} * { background-color: transparent !important; color: inherit !important; }
      ${protectedBody} a, ${protectedBody} a * { color: ${colors.link} !important; }
    `;
  const fontOverride = publisherStyles ? '' : `${protectedBody}, ${protectedBody} * { font-family: ${resolvedFont.stack} !important; }`;
  const lineHeightOverride = publisherStyles ? '' : `${protectedBody} { line-height: ${effective.epub.lineHeight} !important; } ${protectedBody} * { line-height: inherit !important; }`;
  const negativeLetterSpacing = !publisherStyles && effective.epub.letterSpacing < 0
    ? `${protectedBody}, ${protectedBody} * { letter-spacing: ${effective.epub.letterSpacing}em !important; }`
    : '';
  const paragraphAlignment = publisherStyles || effective.epub.typography.textAlign === 'publisher'
    ? ''
    : `text-align: ${effective.epub.typography.textAlign} !important;`;
  return `
    ${fontFace}
    :root { color-scheme: ${colors.colorScheme} !important; }
    ${colorOverride}
    ${fontOverride}
    ${lineHeightOverride}
    ${negativeLetterSpacing}
    ${publisherStyles ? '' : `[data-shuku-smart-paragraph="true"] {
      ${paragraphAlignment}
      margin-block-start: ${effective.epub.typography.paragraphSpacing}em !important;
      margin-block-end: ${effective.epub.typography.paragraphSpacing}em !important;
    }
    .shuku-smart-deduplicate-indent { text-indent: 0 !important; }
    .shuku-smart-auto-indent { text-indent: ${effective.epub.typography.paragraphIndent}em !important; }`}
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
