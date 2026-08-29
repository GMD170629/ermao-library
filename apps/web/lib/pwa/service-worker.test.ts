import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { privateCacheName, privateCacheNamespace } from './private-cache-namespace';

const source = readFileSync(new URL('../../public/sw.js', import.meta.url), 'utf8');
const packageSource = readFileSync(new URL('../../package.json', import.meta.url), 'utf8');
const packageVersion = /"version"\s*:\s*"([^"]+)"/u.exec(packageSource)?.[1];

test('service worker waits for explicit production updates but releases stale localhost workers', () => {
  const installHandler = source.slice(source.indexOf("self.addEventListener('install'"), source.indexOf("self.addEventListener('activate'"));
  assert.match(installHandler, /if \(isLocalDevelopmentHost\(self\.location\.hostname\)\)[\s\S]*self\.skipWaiting\(\)/);
  assert.match(source, /event\.data\?\.type === 'SKIP_WAITING'/);
  assert.doesNotMatch(source, /reloadReaderClients/);
});

test('reader fonts and large reader payloads bypass caches', () => {
  assert.match(source, /function isReaderFont/);
  assert.match(source, /if \(isReaderFont\(url\.pathname\)\) return true/);
  assert.match(source, /isLargeReaderPayload\(url\.pathname\)/);
  assert.match(source, /withoutBasePath\(url\.pathname\)\.startsWith\('\/api\/reader\/'\)/);
  assert.match(source, /if \(isLocalDevelopmentHost\(url\.hostname\)\) return true/);
  assert.match(source, /m4b\|m4a\|mp3\|aac\|ogg\|opus\|flac\|wav/);
  assert.match(source, /assets\\\/\[\^\/\]\+\(\?:\\\/\(stream\|audio\)\)\?\$/);
});

test('PDF.js decoder WASM uses the versioned static resource cache', () => {
  assert.match(source.match(/function isStaticAsset[\s\S]*?\n\}/)?.[0] ?? '', /wasm/);
  assert.match(source, /isStaticAsset\(url\.pathname\)[\s\S]*cacheFirst\(event\.request, STATIC_CACHE\)/);
});

test('service worker scopes shell and API handling to the configured application base path', () => {
  assert.match(source, /const BASE_PATH = new URL\(self\.registration\.scope\)/);
  assert.match(source, /\]\.map\(withBasePath\)/);
  assert.match(source, /withoutBasePath\(url\.pathname\)\.startsWith\('\/api\/'\)/);
  assert.match(source, /cache\.match\(withBasePath\('\/offline'\)\)/);
});

test('service worker caches the shared web shell without a dedicated mobile entry', () => {
  assert.ok(packageVersion);
  assert.match(source, /'\/login'/);
  assert.match(source, /'\/setup'/);
  assert.doesNotMatch(source, /'\/mobile/);
  assert.ok(source.includes(`const FRONTEND_RESOURCE_VERSION = '${packageVersion}';`));
  assert.match(source, /const VERSION = `shuku-pwa-v\$\{FRONTEND_RESOURCE_VERSION\}`/);
});

test('localized web manifest is never pinned in a service-worker cache', () => {
  assert.doesNotMatch(source.match(/const SHELL_URLS = \[[\s\S]*?\]\.map\(withBasePath\)/)?.[0] ?? '', /manifest\.webmanifest/);
  assert.doesNotMatch(source.match(/function isStaticAsset[\s\S]*?\n\}/)?.[0] ?? '', /manifest\.webmanifest/);
});

test('private API and cover caches are partitioned by user and authorization version', () => {
  assert.match(source, /const PRIVATE_CACHE_PREFIX = 'shuku-pwa-private-v1-'/);
  assert.match(source, /event\.data\?\.type === 'SET_PRIVATE_CACHE_NAMESPACE'/);
  assert.match(source, /const nextNamespace = safeCacheNamespacePart\(event\.data\.namespace\)/);
  assert.match(source, /privateCacheName\('api'\)/);
  assert.match(source, /privateCacheName\('cover'\)/);
  assert.match(source, /event\.data\?\.type === 'CLEAR_PRIVATE_CACHES'/);
});

test('reader originals share the service-worker namespace and only obsolete accounts are deleted', () => {
  const namespace = privateCacheNamespace('user.1', 7);
  const currentReader = privateCacheName(namespace, 'reader-original-v1');
  const currentApi = privateCacheName(namespace, 'api');
  const oldReader = privateCacheName(privateCacheNamespace('user.1', 6), 'reader-original-v1');
  const otherUser = privateCacheName(privateCacheNamespace('user.2', 7), 'cover');
  const currentPrefix = `shuku-pwa-private-v1-${namespace}-`;
  const obsolete = [currentReader, currentApi, oldReader, otherUser]
    .filter((cacheName) => cacheName.startsWith('shuku-pwa-private-v1-') && !cacheName.startsWith(currentPrefix));
  assert.deepEqual(obsolete, [oldReader, otherUser]);
  assert.match(source, /obsoletePrivateCacheNames\(keys, nextNamespace\)/);
});

test('forced updates only purge versioned frontend resources and preserve reader storage', () => {
  assert.match(source, /event\.data\?\.type === 'GET_FRONTEND_RESOURCE_VERSION'/);
  assert.match(source, /event\.data\?\.type === 'PURGE_FRONTEND_RESOURCES_AND_ACTIVATE'/);
  assert.match(source, /function clearOldFrontendResourceCaches/);
  assert.match(source, /isFrontendResourceCache\(cacheName\)/);
  assert.doesNotMatch(source, /migrateLegacyPrivateCaches/);
  assert.doesNotMatch(source, /indexedDB/);
  assert.doesNotMatch(source, /keys\.filter\(\(key\) => !key\.startsWith\(VERSION\)\)/);
});

test('the backend resource-version contract always bypasses service-worker API caches', () => {
  assert.match(source, /withoutBasePath\(url\.pathname\) === '\/api\/app-config'/);
});
