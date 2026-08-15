import { copyFile, cp, mkdir, readFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const expectedVersion = '6.1.200';
const packageFile = new URL('../node_modules/pdfjs-dist/package.json', import.meta.url);
const source = new URL('../node_modules/pdfjs-dist/legacy/build/pdf.worker.min.mjs', import.meta.url);
const destination = new URL('../public/vendor/pdfjs/pdf.worker.legacy.min.mjs', import.meta.url);
const wasmSource = new URL('../node_modules/pdfjs-dist/wasm/', import.meta.url);
const wasmDestination = new URL('../public/vendor/pdfjs/wasm/', import.meta.url);
const packageJson = JSON.parse(await readFile(packageFile, 'utf8'));

if (packageJson.version !== expectedVersion) {
  throw new Error(`pdfjs-dist worker version mismatch: expected ${expectedVersion}, found ${packageJson.version}`);
}

await Promise.all([
  mkdir(dirname(fileURLToPath(destination)), { recursive: true }),
  mkdir(fileURLToPath(wasmDestination), { recursive: true })
]);
await Promise.all([
  copyFile(source, destination),
  cp(wasmSource, wasmDestination, { recursive: true, force: true })
]);
