import assert from 'node:assert/strict';
import test from 'node:test';
import { buildManifest, parseManifest, digest } from './ghcr-updates.mjs';
import { dependencyFixture } from './assemble-release-feed.test.mjs';
import { assembleFeed } from './assemble-release-feed.mjs';

test('OCI files stay independent, deterministic and tied to version and architecture', () => {
  const f = dependencyFixture();
  for (const platform of ['linux-x86_64', 'linux-aarch64']) {
    const reference = JSON.parse(f.manifests.get(`shuku-1.0.5-${platform}-v2.json.reference.json`));
    const bytes = buildManifest(reference, name => f.manifests.get(name));
    assert.deepEqual(bytes, buildManifest(reference, name => f.manifests.get(name)));
    const parsed = parseManifest(bytes, digest(bytes), '1.0.5', platform);
    assert.equal(parsed.reference.oci_digest, digest(bytes));
    assert.equal(parsed.files.size, 3);
    assert.throws(() => parseManifest(bytes, `sha256:${'0'.repeat(64)}`, '1.0.5', platform), /digest/);
    assert.throws(() => parseManifest(bytes, digest(bytes), '1.0.6', platform), /identity/);
    const malformed = JSON.parse(bytes); malformed.layers.push(malformed.layers[0]);
    const duplicate = Buffer.from(JSON.stringify(malformed));
    assert.throws(() => parseManifest(duplicate, digest(duplicate), '1.0.5', platform), /descriptor/);
  }
});
test('GHCR feed keeps references separate from legacy clients and preserves pinned digests', () => {
  const f = dependencyFixture(); f.release.assets = [];
  const refs = ['linux-x86_64', 'linux-aarch64'].map(platform => {
    const reference = JSON.parse(f.manifests.get(`shuku-1.0.5-${platform}-v2.json.reference.json`));
    return { ...reference, oci_digest: digest(buildManifest(reference, name => f.manifests.get(name))) };
  });
  const feed = assembleFeed(f.index, () => f.release, () => { throw Error('No Release downloads'); }, new Map([['1.0.5', refs]]));
  assert.deepEqual(feed.releases[0].ghcrDependencyReleases, refs);
  assert.equal(feed.releases[0].dependencyReleases, undefined);
  assert.equal(feed.releases[0].appPackages, undefined);
});
