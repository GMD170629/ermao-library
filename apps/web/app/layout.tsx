import './globals.css';
import type { Metadata, Viewport } from 'next';
import Script from 'next/script';
import { Suspense } from 'react';
import { AppShell } from '../components/layout/app-shell';
import { AudioMiniPlayer } from '../components/audio/audio-mini-player';
import { FeedbackProvider } from '../components/ui/feedback';
import { AudioPlaybackProvider } from '../features/audio/audio-playback-provider';
import { APP_BASE_PATH, withBasePath } from '../lib/base-path';
import { PRODUCT_DESCRIPTION, PRODUCT_NAME } from '../lib/brand';

const basePathFetchBridge = `(() => {
  const basePath = ${JSON.stringify(APP_BASE_PATH)};
  if (!basePath || window.__shukuBasePathFetchInstalled) return;
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    if (typeof input === 'string' && input.startsWith('/api/')) {
      return originalFetch(basePath + input, init);
    }
    return originalFetch(input, init);
  };
  window.__shukuBasePathFetchInstalled = true;
})();`;

export const metadata: Metadata = {
  applicationName: PRODUCT_NAME,
  title: PRODUCT_NAME,
  description: PRODUCT_DESCRIPTION,
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: PRODUCT_NAME
  },
  icons: {
    icon: [
      { url: withBasePath('/favicon.ico'), sizes: 'any' },
      { url: withBasePath('/favicon-16x16.png'), sizes: '16x16', type: 'image/png' },
      { url: withBasePath('/favicon-32x32.png'), sizes: '32x32', type: 'image/png' },
      { url: withBasePath('/icons/icon-192.png'), sizes: '192x192', type: 'image/png' },
      { url: withBasePath('/icons/icon-512.png'), sizes: '512x512', type: 'image/png' }
    ],
    apple: [
      { url: withBasePath('/apple-touch-icon-120x120.png'), sizes: '120x120', type: 'image/png' },
      { url: withBasePath('/apple-touch-icon-152x152.png'), sizes: '152x152', type: 'image/png' },
      { url: withBasePath('/apple-touch-icon-167x167.png'), sizes: '167x167', type: 'image/png' },
      { url: withBasePath('/apple-touch-icon-180x180.png'), sizes: '180x180', type: 'image/png' },
      { url: withBasePath('/apple-touch-icon.png'), sizes: '180x180', type: 'image/png' }
    ],
    other: [
      { rel: 'apple-touch-icon-precomposed', url: withBasePath('/apple-touch-icon-precomposed.png'), sizes: '180x180', type: 'image/png' }
    ]
  }
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: 'cover',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#FBFAF8' },
    { media: '(prefers-color-scheme: dark)', color: '#FBFAF8' }
  ],
  colorScheme: 'light dark'
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <head>
        <link rel="manifest" href={withBasePath('/manifest.webmanifest')} />
        <Script id="shuku-base-path-fetch" strategy="beforeInteractive" dangerouslySetInnerHTML={{ __html: basePathFetchBridge }} />
      </head>
      <body>
        <FeedbackProvider>
          <AudioPlaybackProvider>
            <Suspense fallback={<div className="min-h-screen bg-[var(--shuku-bg)]" />}>
              <AppShell>{children}</AppShell>
              <AudioMiniPlayer />
            </Suspense>
          </AudioPlaybackProvider>
        </FeedbackProvider>
      </body>
    </html>
  );
}
