import { createHash } from 'node:crypto';
import { readFile, readdir } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const EMSCRIPTEN_VERSION = '3.1.74';
const webRoot = resolve(import.meta.dirname, '..');
const chapterCoreRoot = resolve(webRoot, '../../packages/reader-core/native/chapters');
const sourceRoot = join(webRoot, 'chapter-wasm');
const outputRoot = join(webRoot, 'public/vendor/chapter-core');

function digest(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

async function sourceDigest(root) {
  const files = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory() && !entry.name.startsWith('build') && !entry.name.startsWith('.')) await visit(path);
      else if (entry.isFile() && /(?:\.c|\.h|\.cmake|CMakeLists\.txt)$/.test(entry.name)) files.push(path);
    }
  }
  await visit(root);
  files.sort();
  const hash = createHash('sha256');
  for (const path of files) {
    hash.update(path.slice(root.length + 1).replaceAll('\\', '/'));
    hash.update('\0');
    hash.update(await readFile(path));
    hash.update('\0');
  }
  return hash.digest('hex');
}

const manifest = JSON.parse(await readFile(join(outputRoot, 'artifact-manifest.json'), 'utf8'));
if (
  manifest.schemaVersion !== 1
  || manifest.abiVersion !== 1
  || manifest.emscriptenVersion !== EMSCRIPTEN_VERSION
) throw new Error('CHAPTER_WASM_MANIFEST_INVALID');
const moduleBytes = await readFile(join(outputRoot, 'ermao-chapters.mjs'));
const wasmBytes = await readFile(join(outputRoot, 'ermao-chapters.wasm'));
if (manifest.moduleSha256 !== digest(moduleBytes) || manifest.wasmSha256 !== digest(wasmBytes)) {
  throw new Error('CHAPTER_WASM_ARTIFACT_HASH_INVALID');
}
if (manifest.sourceSha256 !== await sourceDigest(chapterCoreRoot)) {
  throw new Error('CHAPTER_WASM_SOURCE_HASH_INVALID');
}
if (manifest.webGlueSha256 !== await sourceDigest(sourceRoot)) {
  throw new Error('CHAPTER_WASM_GLUE_HASH_INVALID');
}
