import type { ReaderTheme } from '@shuku/reader-core';

export const DEFAULT_READER_THEME: ReaderTheme = 'warm';

export const readerThemeSurfaces: Record<ReaderTheme, {
  background: string;
  color: string;
  link: string;
  colorScheme: 'light' | 'dark';
  textClass: string;
  statusBarStyle: 'default' | 'black-translucent';
}> = {
  day: {
    background: '#F7F7F4',
    color: '#1E293B',
    link: '#2563EB',
    colorScheme: 'light',
    textClass: 'text-slate-950',
    statusBarStyle: 'default'
  },
  warm: {
    background: '#FDF6EA',
    color: '#2B2118',
    link: '#B45309',
    colorScheme: 'light',
    textClass: 'text-slate-950',
    statusBarStyle: 'default'
  },
  night: {
    background: '#0F172A',
    color: '#E2E8F0',
    link: '#93C5FD',
    colorScheme: 'dark',
    textClass: 'text-slate-100',
    statusBarStyle: 'black-translucent'
  },
  black: {
    background: '#000000',
    color: '#F8FAFC',
    link: '#93C5FD',
    colorScheme: 'dark',
    textClass: 'text-slate-100',
    statusBarStyle: 'black-translucent'
  }
};

export function isDarkReaderTheme(theme: ReaderTheme) {
  return readerThemeSurfaces[theme].colorScheme === 'dark';
}
