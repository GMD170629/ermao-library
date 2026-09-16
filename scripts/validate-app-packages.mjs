import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { copyFileSync, constants, mkdirSync, readFileSync, readdirSync, lstatSync } from 'node:fs';
import { join, resolve } from 'node:path';

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
  if (files.some(name => name.endsWith("-v2.json.reference.json"))) return validateDependencyPackages(root, version, remote);
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

// Release/feed metadata checks complement the production target-platform validator.
// They enumerate the complete referenced assets rather than assuming a fixed count.
export function validateDependencyReference(value, version, platform) {
  if (!value || value.format !== 2 || value.version !== version || !platforms.includes(platform) ||
      value.environment?.format !== 1 || value.environment.platform !== platform ||
      !/^[a-f0-9]{64}$/.test(value.environment.compatibility) ||
      value.filename !== `shuku-${version}-${platform}-v2.json` ||
      !Number.isSafeInteger(value.size) || value.size <= 0 || value.size > 32 * 1024 ** 2 ||
      !/^[a-f0-9]{64}$/.test(value.sha256)) throw Error('Invalid dependency release reference');
  return value;
}
export function dependencyAssets(reference, bytes) {
  if (bytes.length !== reference.size || createHash('sha256').update(bytes).digest('hex') !== reference.sha256) throw Error('Dependency manifest SHA-256 mismatch');
  const manifest = JSON.parse(bytes);
  const environment = reference.environment;
  if (manifest.protocol !== 2 || manifest.version !== reference.version ||
      manifest.environment?.format !== environment.format || manifest.environment?.platform !== environment.platform ||
      manifest.environment?.compatibility !== environment.compatibility ||
      !/^cpython-311-(x86_64|aarch64)-linux-gnu$/.test(manifest.python_abi) ||
      !manifest.python_abi.includes(environment.platform.slice(6)) ||
      manifest.dependencies?.protocol !== 2 || !Array.isArray(manifest.dependencies.packages) ||
      manifest.dependencies.packages.length > 10000 || !/^[a-f0-9]{64}$/.test(manifest.dependencies.identity) ||
      manifest.code?.filename !== `shuku-${reference.version}-${environment.platform}-code.tar.gz`) throw Error('Invalid dependency release manifest');
  const artifacts = new Map();
  for (const artifact of [reference, manifest.code, ...manifest.dependencies.packages.map(p => p.artifact)]) {
    if (!artifact || !/^[A-Za-z0-9][A-Za-z0-9._+-]{0,240}$/.test(artifact.filename) ||
        !Number.isSafeInteger(artifact.size) || artifact.size <= 0 || artifact.size > 512 * 1024 ** 2 ||
        !/^[a-f0-9]{64}$/.test(artifact.sha256)) throw Error('Invalid dependency asset');
    const prior = artifacts.get(artifact.filename);
    if (prior && (prior.size !== artifact.size || prior.sha256 !== artifact.sha256)) throw Error('Conflicting dependency asset');
    artifacts.set(artifact.filename, artifact);
  }
  return [...artifacts.values()];
}
export function validateDependencyPackages(root, version, remote) {
  const expected = new Set();
  const references = platforms.map(platform => {
    const name = `shuku-${version}-${platform}-v2.json.reference.json`;
    const referenceBytes = readFileSync(join(root, name));
    const reference = validateDependencyReference(JSON.parse(referenceBytes), version, platform);
    expected.add(name);
    if (remote) validateRemoteAsset(remote.assets, name, referenceBytes.length, createHash('sha256').update(referenceBytes).digest('hex'));
    for (const artifact of dependencyAssets(reference, readFileSync(join(root, reference.filename)))) {
      expected.add(artifact.filename);
      const bytes = readFileSync(join(root, artifact.filename));
      if (bytes.length !== artifact.size || createHash('sha256').update(bytes).digest('hex') !== artifact.sha256) throw Error(`Dependency SHA-256 mismatch: ${artifact.filename}`);
      if (remote) validateRemoteAsset(remote.assets, artifact.filename, artifact.size, artifact.sha256);
    }
    return reference;
  });
  if (readdirSync(root).some(name => !expected.has(name))) throw Error('Unexpected dependency release assets');
  return references;
}


export function mergeApplicationAssets(output, roots) {
  const files = new Map();
  for (const root of roots) for (const name of readdirSync(root)) {
    const path = join(root, name);
    if (!lstatSync(path).isFile()) throw Error(`Not a regular asset: ${name}`);
    const bytes = readFileSync(path);
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    const old = files.get(name);
    if (old && (old.size !== bytes.length || old.sha256 !== sha256)) throw Error(`Conflicting architecture asset: ${name}`);
    files.set(name, { path, size: bytes.length, sha256 });
  }
  mkdirSync(output, { recursive: true });
  if (readdirSync(output).length) throw Error('Application output must be empty');
  for (const [name, value] of files) copyFileSync(value.path, join(output, name), constants.COPYFILE_EXCL);
  const first = [...files.keys()].find(name => name.endsWith('-v2.json.reference.json'));
  if (!first) throw Error('Missing dependency release references');
  const version = JSON.parse(readFileSync(join(output, first))).version;
  validateDependencyPackages(output, version);
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (process.argv[2] !== '--merge' || process.argv.length < 6) throw Error('Usage: --merge OUTPUT ARCH1 ARCH2');
  mergeApplicationAssets(process.argv[3], process.argv.slice(4));
}
