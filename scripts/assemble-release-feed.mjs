// Rebuild optional install metadata from published, digest-verified official assets.
// Also used by notes synchronization: it cannot erase published appPackages accidentally.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { dependencyAssets, validateDependencyReference, validateAppManifest, validateRemoteAsset } from './validate-app-packages.mjs';

export function publishedPackages(release, version, readManifest) {
  if (release.isDraft !== false || release.isPrerelease !== false || release.tagName !== `v${version}`) throw Error('Release is not a published stable version');
  const assets = release.assets;
  const expected = ['linux-x86_64', 'linux-aarch64'].map(platform => `shuku-${version}-${platform}.tar.gz`);
  // Historic versions with no app artifacts remain explicitly non-installable.
  if (!assets.some(asset => expected.includes(asset.name) || expected.some(name => asset.name === `${name}.json`))) return [];
  return expected.map(name => {
    const bytes = readManifest(`${name}.json`);
    validateRemoteAsset(assets, `${name}.json`, bytes.length, createHash('sha256').update(bytes).digest('hex'));
    const platform = name.slice(`shuku-${version}-`.length, -'.tar.gz'.length);
    const manifest = validateAppManifest(JSON.parse(bytes), version, platform);
    validateRemoteAsset(assets, name, manifest.size, manifest.sha256);
    return manifest;
  });
}
export function publishedDependencies(release, version, readManifest) {
  if (release.isDraft !== false || release.isPrerelease !== false || release.tagName !== `v${version}`) throw Error('Release is not published');
  if (!release.assets.some(asset => asset.name.startsWith(`shuku-${version}-`) && /-v2\.json/.test(asset.name))) return [];
  return ['linux-x86_64', 'linux-aarch64'].map(platform => {
    const name = `shuku-${version}-${platform}-v2.json.reference.json`;
    const descriptors = release.assets.filter(asset => asset.name === name);
    if (descriptors.length !== 1 || descriptors[0].state !== 'uploaded' || !Number.isSafeInteger(descriptors[0].size) || descriptors[0].size <= 0 || descriptors[0].size > 16384) throw Error('Invalid dependency reference asset');
    const bytes = readManifest(name);
    validateRemoteAsset(release.assets, name, bytes.length, createHash('sha256').update(bytes).digest('hex'));
    const reference = validateDependencyReference(JSON.parse(bytes), version, platform);
    validateRemoteAsset(release.assets, reference.filename, reference.size, reference.sha256);
    for (const artifact of dependencyAssets(reference, readManifest(reference.filename))) {
      validateRemoteAsset(release.assets, artifact.filename, artifact.size, artifact.sha256);
    }
    return reference;
  });
}
export function assembleFeed(index, getRelease, readManifest) {
  return { ...index, releases: index.releases.map(release => {
    const published = getRelease(release.tag);
    const read = name => readManifest(release.tag, name);
    const packages = publishedPackages(published, release.version, read);
    const dependencies = publishedDependencies(published, release.version, read);
    const { appPackages: _old, dependencyReleases: _dependencies, ...notes } = release;
    return { ...notes, ...(packages.length ? { appPackages: packages } : {}), ...(dependencies.length ? { dependencyReleases: dependencies } : {}) };
  }) };
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const file = process.argv[2];
  const directory = mkdtempSync(join(tmpdir(), 'release-manifests-'));
  const gh = args => execFileSync('gh', args, { encoding: 'utf8' });
  try {
    const index = assembleFeed(JSON.parse(readFileSync(file, 'utf8')),
      tag => JSON.parse(gh(['release', 'view', tag, '--repo', 'GMD170629/ermao-library', '--json', 'tagName,isDraft,isPrerelease,assets'])),
      (tag, name) => {
        gh(['release', 'download', tag, '--repo', 'GMD170629/ermao-library', '--pattern', name, '--dir', directory, '--clobber']);
        return readFileSync(join(directory, name));
      });
    writeFileSync(file, JSON.stringify(index, null, 2) + '\n');
  } finally { rmSync(directory, { recursive: true, force: true }); }
}
