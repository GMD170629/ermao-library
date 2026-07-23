import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../../public/sw.js', import.meta.url), 'utf8');

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
  assert.match(source, /withoutBasePath\(url\.pathname\)\.startsWith\('\/api\/reader\/v2\/'\)/);
  assert.match(source, /if \(isLocalDevelopmentHost\(url\.hostname\)\) return true/);
  assert.match(source, /m4b\|m4a\|mp3\|aac\|ogg\|opus\|flac\|wav/);
  assert.match(source, /files\\\/\[\^\/\]\+\(\?:\\\/\(stream\|audio\)\)\?\$/);
});

test('service worker scopes shell and API handling to the configured application base path', () => {
  assert.match(source, /const BASE_PATH = new URL\(self\.registration\.scope\)/);
  assert.match(source, /\]\.map\(withBasePath\)/);
  assert.match(source, /withoutBasePath\(url\.pathname\)\.startsWith\('\/api\/'\)/);
  assert.match(source, /cache\.match\(withBasePath\('\/offline'\)\)/);
});

test('service worker caches the shared web shell without a dedicated mobile entry', () => {
  assert.match(source, /'\/login'/);
  assert.match(source, /'\/setup'/);
  assert.doesNotMatch(source, /'\/mobile/);
  assert.match(source, /const VERSION = 'shuku-pwa-v2\.4\.0'/);
});

test('localized web manifest is never pinned in a service-worker cache', () => {
  assert.doesNotMatch(source.match(/const SHELL_URLS = \[[\s\S]*?\]\.map\(withBasePath\)/)?.[0] ?? '', /manifest\.webmanifest/);
  assert.doesNotMatch(source.match(/function isStaticAsset[\s\S]*?\n\}/)?.[0] ?? '', /manifest\.webmanifest/);
});

test('private API and cover caches are partitioned by user and authorization version', () => {
  assert.match(source, /const PRIVATE_CACHE_PREFIX = `\$\{VERSION\}-private-`/);
  assert.match(source, /event\.data\?\.type === 'SET_PRIVATE_CACHE_NAMESPACE'/);
  assert.match(source, /const nextNamespace = userId && authzVersion \? `\$\{userId\}-\$\{authzVersion\}` : ''/);
  assert.match(source, /privateCacheName\('api'\)/);
  assert.match(source, /privateCacheName\('cover'\)/);
  assert.match(source, /event\.data\?\.type === 'CLEAR_PRIVATE_CACHES'/);
});
