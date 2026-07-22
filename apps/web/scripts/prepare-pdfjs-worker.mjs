import { copyFile, mkdir, readFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const expectedVersion = '6.1.200';
const packageFile = new URL('../node_modules/pdfjs-dist/package.json', import.meta.url);
const source = new URL('../node_modules/pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url);
const destination = new URL('../public/vendor/pdfjs/pdf.worker.min.mjs', import.meta.url);
const packageJson = JSON.parse(await readFile(packageFile, 'utf8'));

if (packageJson.version !== expectedVersion) {
  throw new Error(`pdfjs-dist worker version mismatch: expected ${expectedVersion}, found ${packageJson.version}`);
}

await mkdir(dirname(fileURLToPath(destination)), { recursive: true });
await copyFile(source, destination);

