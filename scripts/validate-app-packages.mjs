import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const platforms = ['linux-x86_64', 'linux-aarch64'];
export function validateAppManifest(value, version, platform) {
  const filename = `shuku-${version}-${platform}.tar.gz`;
  const fields = ['version', 'format', 'environment', 'filename', 'size', 'sha256', 'expanded_size', 'file_count'];
  if (!value || Object.keys(value).some(key => !fields.includes(key)) || !value.environment ||
      Object.keys(value.environment).some(key => !['format', 'platform', 'compatibility'].includes(key))) throw Error('Invalid application manifest fields');
  if (!value || value.version !== version || value.format !== 1 || value.filename !== filename ||
      value.environment?.format !== 1 || value.environment.platform !== platform || !platforms.includes(platform) ||
      !/^[a-f0-9]{64}$/.test(value.environment.compatibility) || !/^[a-f0-9]{64}$/.test(value.sha256) ||
      !Number.isSafeInteger(value.size) || value.size <= 0 || value.size > 512 * 1024 ** 2 ||
      !Number.isSafeInteger(value.expanded_size) || value.expanded_size <= 0 || value.expanded_size > 2 * 1024 ** 3 ||
      !Number.isSafeInteger(value.file_count) || value.file_count <= 0 || value.file_count > 100000) throw Error('Invalid application manifest');
  return value;
}
export function validateRemoteAsset(assets, name, size, digest) {
  const matches = assets.filter(asset => asset.name === name);
  const asset = matches[0];
  if (matches.length !== 1 || asset.state !== 'uploaded' || asset.size !== size || asset.digest !== `sha256:${digest}`) throw Error(`Remote application asset incomplete or corrupt: ${name}`);
}
export function validateAppPackages(root, version, remote) {
  const files = readdirSync(root);
  const packages = platforms.map(platform => {
    const name = `shuku-${version}-${platform}.tar.gz`;
    const manifestBytes = readFileSync(join(root, `${name}.json`));
    const manifest = validateAppManifest(JSON.parse(manifestBytes), version, platform);
    const bytes = readFileSync(join(root, name));
    if (bytes.length !== manifest.size || createHash('sha256').update(bytes).digest('hex') !== manifest.sha256) throw Error(`Application SHA-256 mismatch: ${name}`);
    if (remote) {
      validateRemoteAsset(remote.assets, name, manifest.size, manifest.sha256);
      validateRemoteAsset(remote.assets, `${name}.json`, manifestBytes.length, createHash('sha256').update(manifestBytes).digest('hex'));
    }
    return manifest;
  });
  if (files.length !== 4) throw Error('Unexpected application assets');
  return packages;
}
