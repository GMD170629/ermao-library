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

export function dependencyFixture() {
  const manifests = new Map();
  const release = { tagName: 'v1.0.5', isDraft: false, isPrerelease: false, assets: [] };
  const add = (name, bytes) => {
    bytes = Buffer.from(bytes);
    manifests.set(name, bytes);
    const artifact = { filename: name, size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
    release.assets.push({ name, size: artifact.size, digest: `sha256:${artifact.sha256}`, state: 'uploaded' });
    return artifact;
  };
  const shared = add('demo-1-py3-none-any.whl', 'wheel fixture');
  for (const platform of ['linux-x86_64', 'linux-aarch64']) {
    const environment = { format: 1, platform, compatibility: 'b'.repeat(64) };
    const code = add(`shuku-1.0.5-${platform}-code.tar.gz`, 'code fixture');
    const reference = { format: 2, version: '1.0.5', environment, ...add(`shuku-1.0.5-${platform}-v2.json`, JSON.stringify({
      protocol: 2, version: '1.0.5', environment, python_abi: `cpython-311-${platform.slice(6)}-linux-gnu`, code,
      dependencies: { protocol: 2, identity: 'c'.repeat(64), packages: [{ ecosystem: 'python', artifact: shared }] }
    })) };
    add(`${reference.filename}.reference.json`, JSON.stringify(reference));
  }
  const index = { schemaVersion: 1, releases: [{ version: '1.0.5', tag: 'v1.0.5', notesPath: 'v1.0.5.md' }] };
  const build = () => assembleFeed(index, () => release, (_, name) => manifests.get(name));
  return { release, manifests, index, build };
}
test('protocol 2 feed publishes small references; notes sync reconstructs them', () => {
  const f = dependencyFixture();
  const first = f.build();
  assert.equal(first.releases[0].appPackages, undefined);
  assert.equal(first.releases[0].dependencyReleases.length, 2);
  assert.equal(first.releases[0].dependencyReleases[0].dependencies, undefined);
  f.index.releases[0] = first.releases[0];
  assert.deepEqual(f.build(), first);
});
test('protocol 2 draft, missing wheel, corrupt asset and incompatible manifest refuse feed', () => {
  for (const damage of [f => { f.release.isDraft = true; }, f => { f.release.assets.shift(); },
    f => { f.release.assets[0].digest = 'sha256:bad'; }, f => { f.manifests.set('shuku-1.0.5-linux-x86_64-v2.json', Buffer.from('{}')); },
    f => { const name='shuku-1.0.5-linux-x86_64-v2.json.reference.json'; const value=JSON.parse(f.manifests.get(name)); value.environment.platform='linux-aarch64'; f.manifests.set(name,Buffer.from(JSON.stringify(value))); }]) {
    const f=dependencyFixture(); damage(f); assert.throws(f.build);
  }
});

test('self-consistent wrong protocol, ABI or base environment is rejected', () => {
  for (const change of [m => { m.protocol=1; }, m => { m.python_abi='cpython-311-x86_64-linux-gnu'; }, m => { m.environment.compatibility='d'.repeat(64); }]) {
    const f=dependencyFixture();
    const name='shuku-1.0.5-linux-aarch64-v2.json';
    const manifest=JSON.parse(f.manifests.get(name)); change(manifest);
    const bytes=Buffer.from(JSON.stringify(manifest)); f.manifests.set(name,bytes);
    const digest=createHash('sha256').update(bytes).digest('hex');
    Object.assign(f.release.assets.find(a=>a.name===name),{size:bytes.length,digest:`sha256:${digest}`});
    const reference=JSON.parse(f.manifests.get(`${name}.reference.json`));
    Object.assign(reference,{size:bytes.length,sha256:digest});
    const encoded=Buffer.from(JSON.stringify(reference)); f.manifests.set(`${name}.reference.json`,encoded);
    Object.assign(f.release.assets.find(a=>a.name===`${name}.reference.json`),{size:encoded.length,digest:`sha256:${createHash('sha256').update(encoded).digest('hex')}`});
    assert.throws(f.build,/Invalid dependency release manifest/);
  }
});
