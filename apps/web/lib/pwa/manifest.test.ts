import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

type Manifest = {
  start_url?: string;
  shortcuts?: Array<{ url?: string }>;
};

const manifest = JSON.parse(
  readFileSync(new URL('../../public/manifest.webmanifest', import.meta.url), 'utf8')
) as Manifest;

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
