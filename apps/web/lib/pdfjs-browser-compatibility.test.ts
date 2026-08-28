import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('PDF reader uses the official legacy main module and worker together', async () => {
  const [adapterSource, workerPreparationSource] = await Promise.all([
    readFile('features/reader/v3/adapters/pdf-adapter.ts', 'utf8'),
    readFile('scripts/prepare-pdfjs-worker.mjs', 'utf8')
  ]);

  assert.match(adapterSource, /import\('pdfjs-dist\/legacy\/build\/pdf\.mjs'\)/);
  assert.match(workerPreparationSource, /pdfjs-dist\/legacy\/build\/pdf\.worker\.mjs/);
  assert.match(workerPreparationSource, /pdfjs-dist\/wasm\//);
  assert.match(workerPreparationSource, /pdf\.worker\.legacy\.mjs/);
  assert.match(workerPreparationSource, /public\/vendor\/pdfjs\/wasm\//);
  assert.match(adapterSource, /\/vendor\/pdfjs\/pdf\.worker\.legacy\.mjs\?v=6\.1\.200/);
  assert.match(adapterSource, /wasmUrl:\s*withBasePath\('\/vendor\/pdfjs\/wasm\/'\)/);
});
