import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { assembleFeed } from './assemble-release-feed.mjs';

function fixture() {
  const manifests = new Map();
  const release = { tagName: 'v1.0.5', isDraft: false, isPrerelease: false, assets: [] };
  for (const platform of ['linux-x86_64', 'linux-aarch64']) {
    const filename = `shuku-1.0.5-${platform}.tar.gz`;
    const manifest = { version: '1.0.5', format: 1, filename, size: 7, sha256: 'a'.repeat(64), expanded_size: 20, file_count: 2, environment: { format: 1, platform, compatibility: 'b'.repeat(64) } };
    const bytes = Buffer.from(JSON.stringify(manifest));
    manifests.set(`${filename}.json`, bytes);
    release.assets.push({ name: filename, size: manifest.size, digest: `sha256:${manifest.sha256}`, state: 'uploaded' },
      { name: `${filename}.json`, size: bytes.length, digest: `sha256:${createHash('sha256').update(bytes).digest('hex')}`, state: 'uploaded' });
  }
  const index = { schemaVersion: 1, releases: [{ version: '1.0.5', tag: 'v1.0.5', notesPath: 'v1.0.5.md' }] };
  const build = () => assembleFeed(index, () => release, (_, name) => manifests.get(name));
  return { release, manifests, index, build };
}
test('published metadata survives notes synchronization and preserves old fields', () => {
  const f = fixture();
  const first = f.build();
  assert.equal(first.releases[0].appPackages.length, 2);
  f.index.releases[0] = { ...first.releases[0], notesPath: 'v1.0.5.md' };
  assert.deepEqual(f.build(), first);
  f.release.assets = [];
  assert.equal(f.build().releases[0].appPackages, undefined);
});
test('draft, missing, corrupt and incomplete assets never yield installable metadata', () => {
  for (const change of [f => { f.release.isDraft = true; }, f => { f.release.isPrerelease = true; }, f => { delete f.release.isDraft; },
    f => { f.release.assets.pop(); }, f => { f.release.assets[0].digest = 'sha256:bad'; },
    f => { f.manifests.set([...f.manifests.keys()][0], Buffer.from('{}')); }]) {
    const f = fixture(); change(f); assert.throws(f.build);
  }
});
