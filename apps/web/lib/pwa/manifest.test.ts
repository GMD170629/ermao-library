import assert from 'node:assert/strict';
import test from 'node:test';
import { buildWebManifest } from './manifest';

const manifest = buildWebManifest('zh-CN');

test('installed PWA launches the responsive web application', () => {
  assert.equal(manifest.start_url, '.');
  assert.equal(JSON.stringify(manifest).includes('mobile'), false);
});

test('PWA shortcuts point to normal web routes', () => {
  assert.deepEqual(manifest.shortcuts?.map((shortcut) => shortcut.url), [
    'library',
    'library?upload=1',
    '.'
  ]);
});

test('PWA manifest localizes install metadata and shortcuts', () => {
  const english = buildWebManifest('en-US');
  assert.equal(english.lang, 'en-US');
  assert.equal(english.name, 'Ermao Books');
  assert.deepEqual(english.shortcuts.map((shortcut) => shortcut.name), [
    'Open Library',
    'Upload Books',
    'Continue'
  ]);
  assert.equal(JSON.stringify(english).match(/[\u3400-\u9fff]/u), null);
});
