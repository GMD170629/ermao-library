import { createHash } from 'node:crypto';
import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join, relative, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const EMSCRIPTEN_VERSION = '3.1.74';
const webRoot = resolve(import.meta.dirname, '..');
const sourceRoot = join(webRoot, 'mobi-wasm');
const mobiCoreRoot = resolve(webRoot, '../mobile/native/mobi-core');
const buildRoot = join(webRoot, '.mobi-wasm-build');
const outputRoot = join(webRoot, 'public/vendor/mobi-core');

function run(command, args) {
  const result = spawnSync(command, args, { cwd: webRoot, encoding: 'utf8', stdio: 'pipe', shell: process.platform === 'win32' });
  if (result.status !== 0) throw new Error(`${command} ${args.join(' ')} failed\n${result.stdout}\n${result.stderr}`);
  return `${result.stdout}\n${result.stderr}`;
}

function digest(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

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

const versionOutput = run('emcc', ['--version']);
if (!new RegExp(`emcc \\(Emscripten .*\\) ${EMSCRIPTEN_VERSION.replaceAll('.', '\\.')}`).test(versionOutput)) {
  throw new Error(`Expected Emscripten ${EMSCRIPTEN_VERSION}; refusing a non-reproducible build.\n${versionOutput}`);
}

await rm(buildRoot, { recursive: true, force: true });
await mkdir(buildRoot, { recursive: true });
run('emcmake', ['cmake', '-S', sourceRoot, '-B', buildRoot, '-DCMAKE_BUILD_TYPE=Release']);
run('cmake', ['--build', buildRoot, '--config', 'Release', '--target', 'ermao_mobi_web', '--parallel']);

const modulePath = join(buildRoot, 'ermao-mobi.mjs');
const wasmPath = join(buildRoot, 'ermao-mobi.wasm');
const moduleBytes = await readFile(modulePath);
const wasmBytes = await readFile(wasmPath);
await mkdir(outputRoot, { recursive: true });
await cp(modulePath, join(outputRoot, 'ermao-mobi.mjs'));
await cp(wasmPath, join(outputRoot, 'ermao-mobi.wasm'));
await writeFile(join(outputRoot, 'artifact-manifest.json'), `${JSON.stringify({
  schemaVersion: 1,
  emscriptenVersion: EMSCRIPTEN_VERSION,
  abiVersion: 1,
  moduleSha256: digest(moduleBytes),
  wasmSha256: digest(wasmBytes),
  sourceSha256: await sourceDigest(mobiCoreRoot),
  webGlueSha256: await sourceDigest(sourceRoot)
}, null, 2)}\n`);
