const VERSION = 'shuku-pwa-v2.3.1';
const SHELL_CACHE = `${VERSION}-app-shell`;
const STATIC_CACHE = `${VERSION}-static`;
const PRIVATE_COVER_CACHE = `${VERSION}-private-cover`;
const PRIVATE_API_CACHE = `${VERSION}-private-api`;
const BASE_PATH = new URL(self.registration.scope).pathname.replace(/\/$/, '');
const CACHE_LIMITS = {
  [STATIC_CACHE]: 96,
  [PRIVATE_COVER_CACHE]: 160,
  [PRIVATE_API_CACHE]: 80
};
function withBasePath(pathname) {
  if (!BASE_PATH || !pathname.startsWith('/')) return pathname;
  if (pathname === BASE_PATH || pathname.startsWith(`${BASE_PATH}/`)) return pathname;
  return `${BASE_PATH}${pathname}`;
}

function withoutBasePath(pathname) {
  if (!BASE_PATH) return pathname;
  if (pathname === BASE_PATH) return '/';
  return pathname.startsWith(`${BASE_PATH}/`) ? pathname.slice(BASE_PATH.length) : pathname;
}

const SHELL_URLS = [
  '/offline',
  '/login',
  '/setup',
  '/manifest.webmanifest',
  '/favicon.ico',
  '/favicon-16x16.png',
  '/favicon-32x32.png',
  '/mstile-144x144.png',
  '/apple-touch-icon-120x120.png',
  '/apple-touch-icon-152x152.png',
  '/apple-touch-icon-167x167.png',
  '/apple-touch-icon-180x180.png',
  '/apple-touch-icon.png',
  '/apple-touch-icon-precomposed.png',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/maskable-512.png'
].map(withBasePath);
const PRIVATE_CACHES = [PRIVATE_COVER_CACHE, PRIVATE_API_CACHE];

function debugLog(level, message, details) {
  self.clients.matchAll({ includeUncontrolled: true, type: 'window' })
    .then((clients) => {
      clients.forEach((client) => {
        client.postMessage({
          type: 'PWA_DEBUG_LOG',
          payload: {
            level,
            source: 'service-worker',
            message,
            details,
            time: new Date().toISOString()
          }
        });
      });
    })
    .catch(() => undefined);
}

function isSameOrigin(url) {
  return url.origin === self.location.origin;
}

function isLocalDevelopmentHost(hostname) {
  return hostname === 'localhost' || hostname === '127.0.0.1';
}

function isSensitiveApi(pathname) {
  pathname = withoutBasePath(pathname);
  return pathname.startsWith('/api/auth/')
    || pathname === '/api/auth/me'
    || pathname.includes('/permissions')
    || pathname.includes('/token');
}

function isLargeReaderPayload(pathname) {
  pathname = withoutBasePath(pathname);
  return /\/api\/editions\/[^/]+\/file$/.test(pathname)
    || /\/api\/files\/[^/]+(?:\/(stream|audio))?$/.test(pathname)
    || /\/api\/audio\/[^/]+/.test(pathname)
    || /\/api\/volumes\/[^/]+\/pages\/[^/]+$/.test(pathname)
    || /\.(cbz|zip|epub|pdf|m4b|m4a|mp3|aac|ogg|opus|flac|wav)$/i.test(pathname);
}

function isStaticAsset(pathname) {
  pathname = withoutBasePath(pathname);
  return pathname.startsWith('/_next/static/')
    || pathname.startsWith('/icons/')
    || pathname === '/manifest.webmanifest'
    || /\.(css|js|svg)$/i.test(pathname);
}

function isReaderFont(pathname) {
  pathname = withoutBasePath(pathname);
  return pathname.startsWith('/fonts/reader/') || /\.(woff2?|ttf|otf)$/i.test(pathname);
}

function isCoverRequest(pathname) {
  pathname = withoutBasePath(pathname);
  return /\/api\/works\/[^/]+\/cover(\/|$)/.test(pathname)
    || /\/api\/editions\/[^/]+\/cover(\/|$)/.test(pathname)
    || /\/api\/volumes\/[^/]+\/cover(\/|$)/.test(pathname);
}

function shouldBypass(request) {
  const url = new URL(request.url);
  if (request.method !== 'GET') return true;
  if (!isSameOrigin(url)) return true;
  // Development chunks keep stable URLs while their contents change. Any
  // service-worker cache on localhost can therefore make a normal reload run
  // an old reader bundle and make source fixes appear to have no effect.
  if (isLocalDevelopmentHost(url.hostname)) return true;
  if (isSensitiveApi(url.pathname)) return true;
  if (withoutBasePath(url.pathname).startsWith('/api/reader/v2/')) return true;
  if (isLargeReaderPayload(url.pathname)) return true;
  if (isReaderFont(url.pathname)) return true;
  if (/\.(cbz|zip|epub|pdf|m4b|m4a|mp3|aac|ogg|opus|flac|wav)$/i.test(url.pathname)) return true;
  return false;
}

function offlineApiResponse() {
  return new Response(JSON.stringify({ ok: false, error: { code: 'OFFLINE', message: '当前离线，稍后重试' } }), {
    status: 503,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }
  });
}

async function trimCache(cacheName) {
  const limit = CACHE_LIMITS[cacheName];
  if (!limit) return;
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  if (keys.length <= limit) return;
  await Promise.all(keys.slice(0, keys.length - limit).map((request) => cache.delete(request)));
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    await trimCache(cacheName);
  }
  return response;
}

async function networkFirstPage(request) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    return await fetch(request);
  } catch {
    const url = new URL(request.url);
    return (await cache.match(request)) || (await cache.match(url.pathname)) || (await cache.match(withBasePath('/offline'))) || Response.error();
  }
}

async function networkFirstApi(request) {
  const cache = await caches.open(PRIVATE_API_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) {
      const url = new URL(request.url);
      if (!isSensitiveApi(url.pathname) && !isLargeReaderPayload(url.pathname)) {
        await cache.put(request, response.clone());
        await trimCache(PRIVATE_API_CACHE);
      }
    }
    return response;
  } catch {
    return (await cache.match(request)) || offlineApiResponse();
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const refresh = fetch(request).then(async (response) => {
    if (response.ok) {
      await cache.put(request, response.clone());
      await trimCache(cacheName);
    }
    return response;
  }).catch(() => cached);
  return cached || refresh;
}

async function clearPrivateCaches() {
  await Promise.all(PRIVATE_CACHES.map((cacheName) => caches.delete(cacheName)));
}

self.addEventListener('install', (event) => {
  debugLog('info', 'install', VERSION);
  if (isLocalDevelopmentHost(self.location.hostname)) {
    event.waitUntil(self.skipWaiting());
    return;
  }
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => {
        debugLog('info', 'shell cached', SHELL_URLS.length);
      })
      .catch((error) => {
        debugLog('error', 'install failed', error?.message || String(error));
        throw error;
      })
  );
});

self.addEventListener('activate', (event) => {
  debugLog('info', 'activate', VERSION);
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
      .then(() => debugLog('info', 'clients claimed', VERSION))
      .catch((error) => {
        debugLog('error', 'activate failed', error?.message || String(error));
        throw error;
      })
  );
});

self.addEventListener('fetch', (event) => {
  if (shouldBypass(event.request)) return;

  const url = new URL(event.request.url);
  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(event.request, STATIC_CACHE));
    return;
  }
  if (isCoverRequest(url.pathname)) {
    event.respondWith(staleWhileRevalidate(event.request, PRIVATE_COVER_CACHE));
    return;
  }
  if (withoutBasePath(url.pathname).startsWith('/api/')) {
    event.respondWith(networkFirstApi(event.request));
    return;
  }
  if (event.request.mode === 'navigate' || event.request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(networkFirstPage(event.request));
  }
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    debugLog('info', 'skip waiting requested');
    self.skipWaiting();
  }
  if (event.data?.type === 'CLEAR_PRIVATE_CACHES') {
    debugLog('info', 'clear private caches requested');
    event.waitUntil(clearPrivateCaches().then(() => debugLog('info', 'private caches cleared')));
  }
});
