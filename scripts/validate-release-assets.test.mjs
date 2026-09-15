import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { validateReleaseAssets } from './validate-release-assets.mjs';

test('publication requires both intact packages locally and remotely', t => {
  const root = mkdtempSync(join(tmpdir(), 'release-assets-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const remote = { assets: [] };
  for (const [dir, name] of [['android', 'ermao-library-v1.0.1-android.apk'], ['fnos', 'ermao-books-1.0.1-all.fpk']]) {
    mkdirSync(join(root, dir));
    const digest = createHash('sha256').update('fixture').digest('hex');
    for (const [file, data] of [[name, 'fixture'], [`${name}.sha256`, `${digest}  ${name}\n`]]) {
      writeFileSync(join(root, dir, file), data);
      remote.assets.push({ name: file, state: 'uploaded', size: Buffer.byteLength(data), digest: `sha256:${createHash('sha256').update(data).digest('hex')}` });
    }
  }
  validateReleaseAssets(root, 'v1.0.1', remote);
  assert.throws(() => validateReleaseAssets(root, 'v1.0.1', { assets: remote.assets.slice(0, 2) }), /Remote/);
  const apk = join(root, 'android', 'ermao-library-v1.0.1-android.apk');
  writeFileSync(apk, 'corrupt');
  assert.throws(() => validateReleaseAssets(root, 'v1.0.1'), /SHA-256/);
  writeFileSync(apk, 'fixture');
  rmSync(join(root, 'fnos', 'ermao-books-1.0.1-all.fpk'));
  assert.throws(() => validateReleaseAssets(root, 'v1.0.1'), /Incomplete/);
  rmSync(apk);
  assert.throws(() => validateReleaseAssets(root, 'v1.0.1'), /Incomplete/);
});

for (const version of ['1.0.3', '1.0.4']) {
test(`${version} permits a server-only bundle and still verifies remote digests`, t => {
  const root = mkdtempSync(join(tmpdir(), 'server-release-assets-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(join(root, 'fnos'));
  const name = `ermao-books-${version}-all.fpk`;
  const digest = createHash('sha256').update('fixture').digest('hex');
  const assets = [];
  for (const [file, data] of [[name, 'fixture'], [`${name}.sha256`, `${digest}  ${name}\n`]]) {
    writeFileSync(join(root, 'fnos', file), data);
    assets.push({ name: file, state: 'uploaded', size: Buffer.byteLength(data), digest: `sha256:${createHash('sha256').update(data).digest('hex')}` });
  }
  validateReleaseAssets(root, `v${version}`, { assets });
  assert.throws(() => validateReleaseAssets(root, 'v1.0.5'), /android/);
  assert.throws(() => validateReleaseAssets(root, `v${version}`, { assets: assets.slice(0, 1) }), /Remote/);
  assert.throws(() => validateReleaseAssets(root, `v${version}`, { assets: [...assets, { name: 'old.apk' }] }), /must not contain mobile/);
  writeFileSync(join(root, 'fnos', name), 'corrupt');
  assert.throws(() => validateReleaseAssets(root, `v${version}`), /SHA-256/);
});
}
