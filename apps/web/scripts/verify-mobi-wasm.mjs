import { createHash } from 'node:crypto';
import { readFile, readdir } from 'node:fs/promises';
import { resolve, join, relative } from 'node:path';

const outputRoot = resolve(import.meta.dirname, '../public/vendor/mobi-core');
const sourceRoot = resolve(import.meta.dirname, '../mobi-wasm');
const mobiCoreRoot = resolve(import.meta.dirname, '../../mobile/native/mobi-core');

async function sourceDigest(root) {
  const files = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) await visit(path);
      else if (entry.isFile() && /\.(?:c|h|cmake|txt)$/.test(entry.name)) files.push(path);
    }
  }
  await visit(root);
  files.sort();
  const hash = createHash('sha256');
  for (const path of files) {
    hash.update(relative(root, path).replaceAll('\\', '/'));
    hash.update('\0');
    hash.update(await readFile(path));
    hash.update('\0');
  }
  return hash.digest('hex');
}
const manifest = JSON.parse(await readFile(join(outputRoot, 'artifact-manifest.json'), 'utf8'));
if (manifest.schemaVersion !== 1 || manifest.emscriptenVersion !== '3.1.74' || manifest.abiVersion !== 1) {
  throw new Error('mobi-core artifact manifest contract is invalid');
}
for (const [name, expected] of [['ermao-mobi.mjs', manifest.moduleSha256], ['ermao-mobi.wasm', manifest.wasmSha256]]) {
  const actual = createHash('sha256').update(await readFile(join(outputRoot, name))).digest('hex');
  if (actual !== expected) throw new Error(`${name} does not match artifact-manifest.json`);
}
if (manifest.sourceSha256 !== await sourceDigest(mobiCoreRoot)) {
  throw new Error('mobi-core sources do not match artifact-manifest.json');
}
if (manifest.webGlueSha256 !== await sourceDigest(sourceRoot)) {
  throw new Error('Web mobi-core glue does not match artifact-manifest.json');
}
