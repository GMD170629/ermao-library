'use client';

import type { ReaderTheme } from '@shuku/reader-core';
import { useLayoutEffect } from 'react';
import { readerThemeSurfaces } from '../reader-theme';

function ensureMeta(name: string) {
  const existing = document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
  if (existing) return { meta: existing, created: false };
  const meta = document.createElement('meta');
  meta.setAttribute('name', name);
  document.head.appendChild(meta);
  return { meta, created: true };
}

/** Keeps the iOS standalone chrome and safe-area canvas on the active reader theme. */
export function useReaderPwaSurface(theme: ReaderTheme) {
  useLayoutEffect(() => {
    const themeSurface = readerThemeSurfaces[theme];
    const previousHtmlBackground = document.documentElement.style.backgroundColor;
    const previousBodyBackground = document.body.style.backgroundColor;
    const previousColorScheme = document.documentElement.style.colorScheme;
    const foundThemeColorMetas = Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'));
    const createdThemeColor = foundThemeColorMetas.length === 0 ? ensureMeta('theme-color') : null;
    const themeColorMetas = createdThemeColor ? [createdThemeColor.meta] : foundThemeColorMetas;
    const { meta: statusBarMeta, created: createdStatusBarMeta } = ensureMeta('apple-mobile-web-app-status-bar-style');
    const previousThemeColors = themeColorMetas.map((meta) => meta.content);
    const previousStatusBarStyle = statusBarMeta.content;

    function applySurface() {
      document.documentElement.style.backgroundColor = themeSurface.background;
      document.body.style.backgroundColor = themeSurface.background;
      document.documentElement.style.colorScheme = themeSurface.colorScheme;
      const currentThemeColorMetas = Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'));
      const targetThemeColorMetas = currentThemeColorMetas.length > 0
        ? currentThemeColorMetas
        : [ensureMeta('theme-color').meta];
      targetThemeColorMetas.forEach((meta) => {
        if (meta.content !== themeSurface.background) meta.setAttribute('content', themeSurface.background);
      });
      const currentStatusBarMeta = ensureMeta('apple-mobile-web-app-status-bar-style').meta;
      if (currentStatusBarMeta.content !== themeSurface.statusBarStyle) {
        currentStatusBarMeta.setAttribute('content', themeSurface.statusBarStyle);
      }
    }

    applySurface();
    const frame = window.requestAnimationFrame(applySurface);
    const settleTimer = window.setTimeout(applySurface, 250);

    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(settleTimer);
      document.documentElement.style.backgroundColor = previousHtmlBackground;
      document.body.style.backgroundColor = previousBodyBackground;
      document.documentElement.style.colorScheme = previousColorScheme;
      themeColorMetas.forEach((meta, index) => {
        if (createdThemeColor?.meta === meta) {
          meta.remove();
          return;
        }
        meta.setAttribute('content', previousThemeColors[index]);
      });
      if (createdStatusBarMeta) statusBarMeta.remove();
      else statusBarMeta.setAttribute('content', previousStatusBarStyle);
    };
  }, [theme]);
}
