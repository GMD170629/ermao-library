// Rebuild optional install metadata from published, digest-verified official assets.
// Also used by notes synchronization: it cannot erase published appPackages accidentally.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { validateAppManifest, validateRemoteAsset } from './validate-app-packages.mjs';

export function publishedPackages(release, version, readManifest) {
  if (release.isDraft !== false || release.isPrerelease !== false || release.tagName !== `v${version}`) throw Error('Release is not a published stable version');
  const assets = release.assets;
  const expected = ['linux-x86_64', 'linux-aarch64'].map(platform => `shuku-${version}-${platform}.tar.gz`);
  // Historic versions with no app artifacts remain explicitly non-installable.
  if (!assets.some(asset => asset.name.startsWith(`shuku-${version}-`))) return [];
  return expected.map(name => {
    const bytes = readManifest(`${name}.json`);
    validateRemoteAsset(assets, `${name}.json`, bytes.length, createHash('sha256').update(bytes).digest('hex'));
    const platform = name.slice(`shuku-${version}-`.length, -'.tar.gz'.length);
    const manifest = validateAppManifest(JSON.parse(bytes), version, platform);
    validateRemoteAsset(assets, name, manifest.size, manifest.sha256);
    return manifest;
  });
}
export function assembleFeed(index, getRelease, readManifest) {
  return { ...index, releases: index.releases.map(release => {
    const packages = publishedPackages(getRelease(release.tag), release.version, name => readManifest(release.tag, name));
    const { appPackages: _old, ...notes } = release;
    return packages.length ? { ...notes, appPackages: packages } : notes;
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
