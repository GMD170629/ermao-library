import { serverUpdate } from './validate-release-notes.mjs';
// Rebuild optional install metadata from published, digest-verified official assets.
// Also used by notes synchronization: it cannot erase published appPackages accidentally.
import { readPublishedDependencies } from './ghcr-updates.mjs';
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
export function assembleFeed(index, getRelease, readManifest, ghcr = new Map()) {
  return { ...index, releases: index.releases.map(release => {
    if (serverUpdate(release)) {
      const references = ghcr.get(release.version);
      if (!references || references.length !== 2 || new Set(references.map(item => item.environment.platform)).size !== 2 ||
          !references.every(item => item.version === release.version && ['linux-x86_64', 'linux-aarch64'].includes(item.environment.platform) && /^sha256:[a-f0-9]{64}$/.test(item.oci_digest))) {
        throw Error('code-only requires both digest-verified GHCR architectures');
      }
    }
    const published = getRelease(release.tag);
    if (published === null) {
      if (release === index.releases[0] || ghcr.has(release.version) ||
          ['appPackages', 'dependencyReleases', 'ghcrDependencyReleases'].some(key => release[key]?.length)) {
        throw Error('Installable or latest Release is missing');
      }
      return release; // Historic notes without install metadata need no binary Release.
    }
    const read = name => readManifest(release.tag, name);
    const packages = publishedPackages(published, release.version, read);
    const dependencies = publishedDependencies(published, release.version, read);
    const { appPackages: _old, dependencyReleases: _dependencies, ghcrDependencyReleases: _ghcr, ...notes } = release;
    return { ...notes, ...(ghcr.has(release.version) ? { ghcrDependencyReleases: ghcr.get(release.version) } : {}), ...(packages.length ? { appPackages: packages } : {}), ...(dependencies.length ? { dependencyReleases: dependencies } : {}) };
  }) };
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const file = process.argv[2];
  const directory = mkdtempSync(join(tmpdir(), 'release-manifests-'));
  const gh = args => execFileSync('gh', args, { encoding: 'utf8' });
  try {
    const source = JSON.parse(readFileSync(file, 'utf8'));
    const existing = JSON.parse(Buffer.from(JSON.parse(gh(['api', 'repos/GMD170629/ermao-library/contents/index.json?ref=release-feed'])).content, 'base64').toString('utf8'));
    const availableTags = new Set(gh(['api', '--paginate', 'repos/GMD170629/ermao-library/releases?per_page=100', '--jq', '.[].tag_name']).trim().split('\n'));
    const ghcr = new Map();
    for (const release of source.releases) {
      if (release.version.split('.').map(Number)[0] > 1 ||
          (Number(release.version.split('.')[0]) === 1 && Number(release.version.split('.')[1]) >= 1)) {
        ghcr.set(release.version, await readPublishedDependencies(release.version, {
          verifyBlobs: !existing.releases.find(item => item.version === release.version)?.ghcrDependencyReleases?.length,
          expectedDigests: existing.releases.find(item => item.version === release.version)?.ghcrDependencyReleases?.map(reference => reference.oci_digest),
        }));
      }
    }
    const index = assembleFeed(source,
      tag => {
        if (!availableTags.has(tag)) {
          const previous = existing.releases.find(item => item.tag === tag);
          if (!previous || ['appPackages', 'dependencyReleases', 'ghcrDependencyReleases'].some(key => previous[key]?.length)) throw Error(`Published Release disappeared: ${tag}`);
          return null;
        }
        return JSON.parse(gh(['release', 'view', tag, '--repo', 'GMD170629/ermao-library', '--json', 'tagName,isDraft,isPrerelease,assets']));
      },
      (tag, name) => {
        gh(['release', 'download', tag, '--repo', 'GMD170629/ermao-library', '--pattern', name, '--dir', directory, '--clobber']);
        return readFileSync(join(directory, name));
      }, ghcr);
    writeFileSync(file, JSON.stringify(index, null, 2) + '\n');
  } finally { rmSync(directory, { recursive: true, force: true }); }
}
