import type { ReaderTheme } from '@shuku/reader-core';
import { visualTokens } from '../../generated/visual-tokens';

export const DEFAULT_READER_THEME: ReaderTheme = 'warm';

type ReaderThemeSurface = {
  background: string;
  color: string;
  link: string;
  accent: string;
  colorScheme: 'light' | 'dark';
  textClass: string;
  statusBarStyle: 'default' | 'black-translucent';
};

const readerThemeBehavior: Record<ReaderTheme, Pick<ReaderThemeSurface, 'textClass' | 'statusBarStyle'>> = {
  day: { textClass: 'text-slate-950', statusBarStyle: 'black-translucent' },
  warm: { textClass: 'text-slate-950', statusBarStyle: 'black-translucent' },
  green: { textClass: 'text-slate-950', statusBarStyle: 'black-translucent' },
  night: { textClass: 'text-slate-100', statusBarStyle: 'black-translucent' },
  black: { textClass: 'text-slate-100', statusBarStyle: 'black-translucent' }
};

function readerSurface(theme: ReaderTheme): ReaderThemeSurface {
  const palette = visualTokens.reader.themes[theme];
  return {
    background: palette.canvas,
    color: palette.textPrimary,
    link: palette.link,
    accent: palette.accent,
    colorScheme: palette.colorScheme,
    ...readerThemeBehavior[theme]
  };
}

export const readerThemeSurfaces: Record<ReaderTheme, ReaderThemeSurface> = {
  day: readerSurface('day'),
  warm: readerSurface('warm'),
  green: readerSurface('green'),
  night: readerSurface('night'),
  black: readerSurface('black')
};

export function isDarkReaderTheme(theme: ReaderTheme) {
  return readerThemeSurfaces[theme].colorScheme === 'dark';
}

export function resolveReaderTheme(theme: ReaderTheme, mode: 'manual' | 'system', systemDark: boolean): ReaderTheme {
  if (mode === 'manual') return theme;
  return systemDark ? 'night' : 'day';
}
