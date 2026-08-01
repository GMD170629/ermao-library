import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';

const webRoot = path.resolve(import.meta.dirname, '..');
const repositoryRoot = path.resolve(webRoot, '../..');

test('development entry points use webpack to avoid stalled authenticated route compilation', async () => {
  const packageJson = JSON.parse(await readFile(path.join(webRoot, 'package.json'), 'utf8')) as {
    scripts?: Record<string, string>;
  };
  const devTestScript = await readFile(path.join(repositoryRoot, 'scripts/dev-test.sh'), 'utf8');

  assert.match(packageJson.scripts?.dev ?? '', /next dev --webpack(?:\s|$)/);
  assert.match(packageJson.scripts?.['dev:ios'] ?? '', /next dev --webpack(?:\s|$)/);
  assert.match(devTestScript, /next dev --webpack -H 127\.0\.0\.1/);
});
