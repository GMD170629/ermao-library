import type { AppLocale } from '../../i18n/config';
import { translateMessage } from '../../i18n/messages';
import { PRODUCT_DESCRIPTION, PRODUCT_NAME } from '../brand';

export function buildWebManifest(locale: AppLocale) {
  const t = (source: string) => translateMessage(locale, source);
  return {
    name: t(PRODUCT_NAME),
    short_name: t(PRODUCT_NAME),
    description: t(PRODUCT_DESCRIPTION),
    id: '.',
    start_url: '.',
    scope: './',
    display: 'standalone',
    orientation: 'any',
    lang: locale,
    dir: 'ltr',
    theme_color: '#F7F1E8',
    background_color: '#F7F1E8',
    categories: ['books', 'productivity', 'utilities'],
    icons: [
      { src: 'favicon-32x32.png', sizes: '32x32', type: 'image/png' },
      { src: 'mstile-144x144.png', sizes: '144x144', type: 'image/png' },
      { src: 'apple-touch-icon-152x152.png', sizes: '152x152', type: 'image/png' },
      { src: 'apple-touch-icon-167x167.png', sizes: '167x167', type: 'image/png' },
      { src: 'apple-touch-icon.png', sizes: '180x180', type: 'image/png' },
      { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: 'icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
    ],
    shortcuts: [
      {
        name: t('打开书架'),
        short_name: t('书架'),
        description: t('直接打开全部图书'),
        url: 'library',
        icons: [{ src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' }]
      },
      {
        name: t('上传读物'),
        short_name: t('上传'),
        description: t('打开图书上传入口'),
        url: 'library?upload=1',
        icons: [{ src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' }]
      },
      {
        name: t('继续'),
        short_name: t('继续'),
        description: t('回到首页继续上次的阅读、看漫画或听书'),
        url: '.',
        icons: [{ src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' }]
      }
    ]
  };
}

