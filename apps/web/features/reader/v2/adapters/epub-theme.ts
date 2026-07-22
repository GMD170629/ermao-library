import type { ReaderPreferences } from '@shuku/reader-core';
import { readerThemeSurfaces } from '../../reader-theme';
import { fallbackEpubFont, type EpubFontResolution } from './epub-font';

export function epubSurfaceColor(preferences: ReaderPreferences) {
  return readerThemeSurfaces[preferences.appearance.theme].background;
}

export function epubSurfaceTextColor(preferences: ReaderPreferences) {
  return readerThemeSurfaces[preferences.appearance.theme].color;
}

function epubVerticalSpacing(preferences: ReaderPreferences) {
  return preferences.epub.flow === 'paginated'
    ? 'clamp(32px, 5vh, 64px)'
    : 'clamp(28px, 4vh, 56px)';
}

export function createEpubThemeSnapshot(preferences: ReaderPreferences, resolvedFont = fallbackEpubFont(preferences.epub.fontFamily)) {
  const tokens = readerThemeSurfaces[preferences.appearance.theme];
  const maxWidth = Math.max(600, Math.min(1350, Math.round(preferences.epub.pageWidth)));
  const fontSize = Math.max(14, Math.min(30, Math.round(preferences.epub.fontSize)));
  const lineHeight = Math.max(1.4, Math.min(2.4, preferences.epub.lineHeight));
  const verticalSpacing = epubVerticalSpacing(preferences);
  const fontFace = resolvedFont.embedded
    ? `@font-face { font-family: "${resolvedFont.embedded.family}"; src: url("${resolvedFont.embedded.url}") format("woff2"); font-display: swap; font-style: normal; font-weight: 400; }`
    : '';
  const hiddenScrollbar = preferences.epub.flow === 'scrolled'
    ? `
      html, body { scrollbar-width: none !important; -ms-overflow-style: none !important; }
      html::-webkit-scrollbar, body::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }
    `
    : '';
  // :is() adopts the strongest branch specificity while the universal branch
  // matches. This lets one late snapshot beat hostile author !important rules
  // without walking and rewriting the whole document on every theme change.
  const protectedBody = 'body:is(#shuku-theme-guard#shuku-theme-guard#shuku-theme-guard, *)';

  return `
    ${fontFace}
    ${hiddenScrollbar}
    :root {
      color-scheme: ${tokens.colorScheme} !important;
      --shuku-reader-background: ${tokens.background};
      --shuku-reader-color: ${tokens.color};
      --shuku-reader-link: ${tokens.link};
      --shuku-reader-font-size: ${fontSize}px;
      --shuku-reader-line-height: ${lineHeight};
      --shuku-reader-page-width: ${maxWidth}px;
      --shuku-reader-font-family: ${resolvedFont.stack};
    }
    html, ${protectedBody} {
      background: var(--shuku-reader-background) !important;
      color: var(--shuku-reader-color) !important;
    }
    html {
      font-size: var(--shuku-reader-font-size) !important;
    }
    ${protectedBody} {
      box-sizing: border-box !important;
      margin: 0 !important;
      max-width: none !important;
      padding-inline: 24px !important;
      padding-top: ${verticalSpacing} !important;
      padding-bottom: ${verticalSpacing} !important;
      font-family: var(--shuku-reader-font-family) !important;
      font-size: var(--shuku-reader-font-size) !important;
      font-synthesis: none !important;
      line-height: var(--shuku-reader-line-height) !important;
    }
    ${protectedBody}, ${protectedBody} * {
      font-family: var(--shuku-reader-font-family) !important;
    }
    ${protectedBody} * {
      line-height: inherit !important;
    }
    ${protectedBody} * {
      background-color: transparent !important;
      color: inherit !important;
    }
    ${protectedBody} > div, ${protectedBody} > section, ${protectedBody} > article, ${protectedBody} > main,
    ${protectedBody} .calibre, ${protectedBody} .chapter, ${protectedBody} .section,
    ${protectedBody} [style*="background"], ${protectedBody} [bgcolor] {
      background: transparent !important;
      background-color: transparent !important;
      color: inherit !important;
    }
    ${protectedBody} a { color: var(--shuku-reader-link) !important; }
    img, svg, video { max-width: 100% !important; height: auto !important; }
  `.trim();
}

export function applyEpubThemeSnapshot(document: Document, preferences: ReaderPreferences, resolvedFont?: EpubFontResolution) {
  const head = document.head ?? document.querySelector('head');
  if (!head) return;
  let style = head.querySelector<HTMLStyleElement>('style[data-shuku-reader-theme="v2"]');
  if (!style) {
    const namespace = document.documentElement?.namespaceURI;
    style = namespace
      ? document.createElementNS(namespace, 'style') as HTMLStyleElement
      : document.createElement('style');
    style.setAttribute('data-shuku-reader-theme', 'v2');
    head.append(style);
  }
  style.textContent = createEpubThemeSnapshot(preferences, resolvedFont);
}

/**
 * epub.js applies pagination geometry as inline styles after spine hooks run.
 * This is the one post-layout writer for the page frame: it restores the
 * centered single-page measure and gives the text a stable vertical safe area.
 */
export function applyEpubDocumentSpacing(document: Document, preferences: ReaderPreferences) {
  const body = document.body;
  if (!body) return;
  const verticalSpacing = epubVerticalSpacing(preferences);

  body.style.setProperty('box-sizing', 'border-box', 'important');
  // The outer rendition viewport owns centering. A paginated EPUB iframe is
  // intentionally expanded to the width of every generated column; centering
  // or max-sizing body inside that expanded iframe shifts the column track and
  // makes two fragments appear in the visible viewport.
  body.style.setProperty('margin-left', '0', 'important');
  body.style.setProperty('margin-right', '0', 'important');
  body.style.setProperty('max-width', 'none', 'important');
  body.style.setProperty('padding-top', verticalSpacing, 'important');
  body.style.setProperty('padding-bottom', verticalSpacing, 'important');
  body.dataset.shukuPageLayout = preferences.epub.flow === 'paginated' ? 'single-centered' : 'scrolled-centered';
}
