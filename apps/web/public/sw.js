const FRONTEND_RESOURCE_VERSION = '0.5.5';
const VERSION = `shuku-pwa-v${FRONTEND_RESOURCE_VERSION}`;
const SHELL_CACHE = `${VERSION}-app-shell`;
const STATIC_CACHE = `${VERSION}-static`;
const PRIVATE_CACHE_PREFIX = 'shuku-pwa-private-v1-';
const LEGACY_PRIVATE_CACHE_PATTERN = /^shuku-pwa-v\d+\.\d+\.\d+-private-(.+)$/;
const FRONTEND_RESOURCE_CACHE_PATTERN = /^shuku-pwa-v\d+\.\d+\.\d+-(?:app-shell|static)$/;
let privateCacheNamespace = '';
const BASE_PATH = new URL(self.registration.scope).pathname.replace(/\/$/, '');
const CACHE_LIMITS = {
  [STATIC_CACHE]: 96,
  cover: 160,
  api: 80
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
function safeCacheNamespacePart(value) {
  return String(value ?? '').replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 160);
}

function privateCacheName(kind) {
  return privateCacheNamespace ? `${PRIVATE_CACHE_PREFIX}${privateCacheNamespace}-${kind}` : '';
}

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

function isFrontendResourceCache(cacheName) {
  return FRONTEND_RESOURCE_CACHE_PATTERN.test(cacheName);
}

function isLargeReaderPayload(pathname) {
  pathname = withoutBasePath(pathname);
  return /\/api\/resources\/[^/]+\/file$/.test(pathname)
    || /\/api\/assets\/[^/]+(?:\/(stream|audio))?$/.test(pathname)
    || /\/api\/audio\/[^/]+/.test(pathname)
    || /\/api\/resources\/[^/]+\/pages\/[^/]+$/.test(pathname)
    || /\.(cbz|zip|epub|pdf|m4b|m4a|mp3|aac|ogg|opus|flac|wav)$/i.test(pathname);
}

function isStaticAsset(pathname) {
  pathname = withoutBasePath(pathname);
  return pathname.startsWith('/_next/static/')
    || pathname.startsWith('/icons/')
    || /\.(css|js|svg|wasm)$/i.test(pathname);
}

function isReaderFont(pathname) {
  pathname = withoutBasePath(pathname);
  return pathname.startsWith('/fonts/reader/') || /\.(woff2?|ttf|otf)$/i.test(pathname);
}

function isCoverRequest(pathname) {
  pathname = withoutBasePath(pathname);
  return /\/api\/books\/[^/]+\/cover(\/|$)/.test(pathname)
    || /\/api\/resources\/[^/]+\/cover(\/|$)/.test(pathname);
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
  if (withoutBasePath(url.pathname) === '/api/app-config') return true;
  if (withoutBasePath(url.pathname).startsWith('/api/reader/')) return true;
  if (isLargeReaderPayload(url.pathname)) return true;
  if (isReaderFont(url.pathname)) return true;
  if (/\.(cbz|zip|epub|pdf|m4b|m4a|mp3|aac|ogg|opus|flac|wav)$/i.test(url.pathname)) return true;
  return false;
}

function offlineApiResponse() {
  return new Response(JSON.stringify({ ok: false, error: { code: 'OFFLINE', message: '当前网络不可用' } }), {
    status: 503,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }
  });
}

async function trimCache(cacheName, kind) {
  const limit = CACHE_LIMITS[kind] ?? CACHE_LIMITS[cacheName];
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
    await trimCache(cacheName, 'static');
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
  const cacheName = privateCacheName('api');
  if (!cacheName) return fetch(request).catch(() => offlineApiResponse());
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) {
      const url = new URL(request.url);
      if (!isSensitiveApi(url.pathname) && !isLargeReaderPayload(url.pathname)) {
        await cache.put(request, response.clone());
        await trimCache(cacheName, 'api');
      }
    }
    return response;
  } catch {
    return (await cache.match(request)) || offlineApiResponse();
  }
}

async function staleWhileRevalidate(request, cacheName) {
  if (!cacheName) return fetch(request);
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const refresh = fetch(request).then(async (response) => {
    if (response.ok) {
      await cache.put(request, response.clone());
      await trimCache(cacheName, 'cover');
    }
    return response;
  }).catch(() => cached);
  return cached || refresh;
}

async function clearPrivateCaches() {
  const keys = await caches.keys();
  await Promise.all(keys
    .filter((cacheName) => cacheName.startsWith(PRIVATE_CACHE_PREFIX) || LEGACY_PRIVATE_CACHE_PATTERN.test(cacheName))
    .map((cacheName) => caches.delete(cacheName)));
}

async function migrateLegacyPrivateCaches() {
  const keys = await caches.keys();
  for (const legacyName of keys) {
    const match = LEGACY_PRIVATE_CACHE_PATTERN.exec(legacyName);
    if (!match) continue;
    const targetName = `${PRIVATE_CACHE_PREFIX}${match[1]}`;
    const [legacyCache, targetCache] = await Promise.all([caches.open(legacyName), caches.open(targetName)]);
    const requests = await legacyCache.keys();
    for (const request of requests) {
      const response = await legacyCache.match(request);
      if (response) await targetCache.put(request, response);
    }
    await caches.delete(legacyName);
  }
}

async function clearOldFrontendResourceCaches() {
  const keys = await caches.keys();
  await Promise.all(keys
    .filter((cacheName) => isFrontendResourceCache(cacheName) && cacheName !== SHELL_CACHE && cacheName !== STATIC_CACHE)
    .map((cacheName) => caches.delete(cacheName)));
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
    migrateLegacyPrivateCaches()
      .then(() => clearOldFrontendResourceCaches())
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
    event.respondWith(staleWhileRevalidate(event.request, privateCacheName('cover')));
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
  if (event.data?.type === 'GET_FRONTEND_RESOURCE_VERSION') {
    event.ports[0]?.postMessage({ version: FRONTEND_RESOURCE_VERSION });
  }
  if (event.data?.type === 'PURGE_FRONTEND_RESOURCES_AND_ACTIVATE') {
    debugLog('info', 'forced frontend resource purge requested');
    event.waitUntil(
      clearOldFrontendResourceCaches()
        .then(() => {
          event.ports[0]?.postMessage({ ok: true });
          return self.skipWaiting();
        })
    );
  }
  if (event.data?.type === 'SKIP_WAITING') {
    debugLog('info', 'skip waiting requested');
    self.skipWaiting();
  }
  if (event.data?.type === 'CLEAR_PRIVATE_CACHES') {
    debugLog('info', 'clear private caches requested');
    privateCacheNamespace = '';
    event.waitUntil(clearPrivateCaches().then(() => debugLog('info', 'private caches cleared')));
  }
  if (event.data?.type === 'SET_PRIVATE_CACHE_NAMESPACE') {
    const userId = safeCacheNamespacePart(event.data.userId);
    const authzVersion = safeCacheNamespacePart(event.data.authzVersion);
    const nextNamespace = userId && authzVersion ? `${userId}-${authzVersion}` : '';
    if (nextNamespace && nextNamespace !== privateCacheNamespace) {
      privateCacheNamespace = nextNamespace;
      event.waitUntil(
        caches.keys()
          .then((keys) => Promise.all(
            keys
              .filter((cacheName) => cacheName.startsWith(PRIVATE_CACHE_PREFIX) && !cacheName.startsWith(`${PRIVATE_CACHE_PREFIX}${nextNamespace}-`))
              .map((cacheName) => caches.delete(cacheName))
          ))
          .then(() => debugLog('info', 'private cache namespace updated', nextNamespace))
      );
    }
  }
});
