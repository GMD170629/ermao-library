import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdtempSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { dependencyAssets, validateDependencyReference, validateDependencyPackages } from './validate-app-packages.mjs';

export const repository = 'ghcr.io/gmd170629/ermao-library-updates';
const api = `https://${repository.replace('ghcr.io/', 'ghcr.io/v2/')}`;
const mediaType = 'application/vnd.oci.image.manifest.v1+json';
const artifactType = 'application/vnd.ermao.update.v2';
export const digest = bytes => `sha256:${createHash('sha256').update(bytes).digest('hex')}`;
const tagFor = (version, platform) => `v${version}-${platform === 'linux-x86_64' ? 'amd64' : 'arm64'}`;

export function buildManifest(reference, read) {
  const files = dependencyAssets(reference, read(reference.filename));
  return Buffer.from(JSON.stringify({ schemaVersion: 2, mediaType, artifactType,
    config: { mediaType: 'application/vnd.oci.empty.v1+json', digest: digest('{}'), size: 2 },
    layers: files.map(file => ({ mediaType: 'application/octet-stream', digest: `sha256:${file.sha256}`, size: file.size,
      annotations: { 'org.opencontainers.image.title': file.filename } })),
    annotations: { 'org.opencontainers.image.source': 'https://github.com/GMD170629/ermao-library',
      'org.opencontainers.image.version': reference.version, 'io.ermao.platform': reference.environment.platform,
      'io.ermao.reference': JSON.stringify(reference) },
  }));
}

export function parseManifest(bytes, expected, version, platform) {
  if (digest(bytes) !== expected) throw Error('OCI manifest digest mismatch');
  const manifest = JSON.parse(bytes);
  if (manifest.schemaVersion !== 2 || manifest.mediaType !== mediaType || manifest.artifactType !== artifactType ||
      manifest.annotations?.['org.opencontainers.image.version'] !== version || manifest.annotations?.['io.ermao.platform'] !== platform ||
      !Array.isArray(manifest.layers) || manifest.layers.length > 10002) throw Error('Invalid OCI manifest identity');
  const reference = validateDependencyReference(JSON.parse(manifest.annotations['io.ermao.reference']), version, platform);
  const files = new Map();
  for (const item of manifest.layers) {
    const name = item.annotations?.['org.opencontainers.image.title'];
    if (!/^[A-Za-z0-9][A-Za-z0-9._+-]{0,240}$/.test(name ?? '') || files.has(name) ||
        !/^sha256:[a-f0-9]{64}$/.test(item.digest) || !Number.isSafeInteger(item.size) || item.size <= 0 || item.size > 512 * 1024 ** 2) throw Error('Invalid OCI descriptor');
    files.set(name, item);
  }
  const descriptor = files.get(reference.filename);
  if (descriptor?.digest !== `sha256:${reference.sha256}` || descriptor.size !== reference.size) throw Error('Invalid OCI reference');
  return { reference: { ...reference, oci_digest: expected }, files };
}

async function anonymousRead(path, limit, expected) {
  const auth = await fetch('https://ghcr.io/token?service=ghcr.io&scope=repository%3Agmd170629%2Fermao-library-updates%3Apull', { redirect: 'error', signal: AbortSignal.timeout(30000) });
  if (!auth.ok) throw Error(`GHCR anonymous access failed: ${auth.status}`);
  const { token } = await auth.json();
  if (typeof token !== 'string' || !token || token.length > 16384) throw Error('Invalid GHCR token');
  let response = await fetch(`${api}/${path}`, { redirect: 'manual', headers: { Authorization: `Bearer ${token}`, Accept: mediaType }, signal: AbortSignal.timeout(600000) });
  if ([301,302,303,307,308].includes(response.status)) {
    const location = new URL(response.headers.get('location'));
    if (!path.startsWith('blobs/') || location.protocol !== 'https:' || location.hostname !== 'pkg-containers.githubusercontent.com' || location.username || location.password || location.port) throw Error('Untrusted registry redirect');
    response = await fetch(location, { redirect: 'error', signal: AbortSignal.timeout(600000) });
  }
  if (!response.ok) throw Error(`GHCR read failed: ${response.status}`);
  const hash = createHash('sha256');
  const chunks = []; let size = 0;
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > limit) throw Error('GHCR size limit');
    hash.update(chunk);
    // Binary validation streams without keeping whole dependency archives in memory.
    if (!expected) chunks.push(chunk);
  }
  const actual = `sha256:${hash.digest('hex')}`;
  if (expected && (actual !== expected || size !== limit)) throw Error('GHCR blob mismatch');
  return { bytes: expected ? undefined : Buffer.concat(chunks), digest: actual };
}

export async function readPublishedDependencies(version, { verifyBlobs = false, expectedDigests } = {}) {
  const references = [];
  for (const [i, platform] of ['linux-x86_64', 'linux-aarch64'].entries()) {
    const locator = expectedDigests?.[i] ?? tagFor(version, platform);
    const result = await anonymousRead(`manifests/${locator}`, 4 * 1024 ** 2);
    if (expectedDigests && result.digest !== locator) throw Error('Registry changed manifest');
    const { reference, files } = parseManifest(result.bytes, result.digest, version, platform);
    const manifest = await anonymousRead(`blobs/sha256:${reference.sha256}`, reference.size);
    const expected = dependencyAssets(reference, manifest.bytes);
    if (files.size !== expected.length) throw Error('Unexpected OCI files');
    for (const item of expected) {
      const descriptor = files.get(item.filename);
      if (descriptor?.digest !== `sha256:${item.sha256}` || descriptor.size !== item.size) throw Error('OCI file mismatch');
      if (verifyBlobs) await anonymousRead(`blobs/${descriptor.digest}`, item.size, descriptor.digest);
    }
    references.push(reference);
  }
  return references;
}

async function publish(root, version) {
  const references = validateDependencyPackages(root, version);
  const scratch = mkdtempSync(join(tmpdir(), 'ghcr-updates-'));
  const run = args => execFileSync('oras', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  const expectedDigests = [];
  try {
    writeFileSync(join(scratch, 'config.json'), '{}');
    for (const reference of references) {
      const read = name => readFileSync(join(root, name));
      const bytes = buildManifest(reference, read);
      const target = `${repository}:${tagFor(version, reference.environment.platform)}`;
      let existing;
      try { existing = run(['manifest', 'fetch', '--descriptor', target]); }
      catch (error) {
        // Auth/network errors are not evidence that a tag is absent.
        if (!/MANIFEST_UNKNOWN|manifest unknown|not found/i.test(String(error.stderr))) throw error;
      }
      if (existing && JSON.parse(existing).digest !== digest(bytes)) throw Error(`Refusing to overwrite ${target}`);
      if (!existing) {
        run(['blob', 'push', repository, join(scratch, 'config.json')]);
        for (const file of dependencyAssets(reference, read(reference.filename))) run(['blob', 'push', repository, join(root, file.filename)]);
        writeFileSync(join(scratch, 'manifest.json'), bytes);
        run(['manifest', 'push', target, join(scratch, 'manifest.json')]);
      }
      expectedDigests.push(digest(bytes));
    }
    await readPublishedDependencies(version, { verifyBlobs: true, expectedDigests });
    console.log('GHCR manifests and all blobs verified anonymously.');
  } finally { rmSync(scratch, { recursive: true, force: true }); }
}
export async function downloadPublished(version, output) {
  const references = await readPublishedDependencies(version, { verifyBlobs: true });
  mkdirSync(output, { recursive: true });
  for (const reference of references) {
    execFileSync('oras', ['pull', `${repository}@${reference.oci_digest}`, '--output', output], { stdio: 'inherit' });
    const { oci_digest: _digest, ...local } = reference;
    writeFileSync(join(output, `${reference.filename}.reference.json`), JSON.stringify(local) + '\n');
  }
  validateDependencyPackages(output, version);
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (process.argv[2] === '--download') await downloadPublished(process.argv[3], resolve(process.argv[4]));
  else await publish(resolve(process.argv[2]), process.argv[3]);
}
