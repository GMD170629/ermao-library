import { validateAppPackages } from './validate-app-packages.mjs';
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
  addApplications(root, '1.0.1', remote.assets);
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
  addApplications(root, version, assets);
  validateReleaseAssets(root, `v${version}`, { assets });
  assert.throws(() => validateReleaseAssets(root, 'v1.0.5'), /android/);
  assert.throws(() => validateReleaseAssets(root, `v${version}`, { assets: assets.slice(0, 1) }), /Remote/);
  assert.throws(() => validateReleaseAssets(root, `v${version}`, { assets: [...assets, { name: 'old.apk' }] }), /must not contain mobile/);
  writeFileSync(join(root, 'fnos', name), 'corrupt');
  assert.throws(() => validateReleaseAssets(root, `v${version}`), /SHA-256/);
});
}

function addApplications(root, version, assets) {
  mkdirSync(join(root, 'application'));
  for (const platform of ['linux-x86_64', 'linux-aarch64']) {
    const name = `shuku-${version}-${platform}.tar.gz`;
    const digest = createHash('sha256').update('fixture').digest('hex');
    const manifest = { version, format: 1, filename: name, size: 7, sha256: digest, expanded_size: 20, file_count: 2, environment: { format: 1, platform, compatibility: 'b'.repeat(64) } };
    for (const [file, data] of [[name, 'fixture'], [`${name}.json`, JSON.stringify(manifest)]]) {
      writeFileSync(join(root, 'application', file), data);
      assets.push({ name: file, size: Buffer.byteLength(data), state: 'uploaded', digest: `sha256:${createHash('sha256').update(data).digest('hex')}` });
    }
  }
}

test('application assets are mandatory and digest checked', t => {
  const root = mkdtempSync(join(tmpdir(), 'application-assets-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  addApplications(root, '1.0.5', []);
  const directory = join(root, 'application');
  assert.equal(validateAppPackages(directory, '1.0.5').length, 2);
  writeFileSync(join(directory, 'shuku-1.0.5-linux-x86_64.tar.gz'), 'bad');
  assert.throws(() => validateAppPackages(directory, '1.0.5'), /SHA-256/);
  rmSync(join(directory, 'shuku-1.0.5-linux-x86_64.tar.gz.json'));
  assert.throws(() => validateAppPackages(directory, '1.0.5'));
});
