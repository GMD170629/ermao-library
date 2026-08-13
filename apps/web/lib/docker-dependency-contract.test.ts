import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';

const webRoot = path.resolve(import.meta.dirname, '..');

test('Docker builds install the pinned Readium Web packages', async () => {
  const packageJson = JSON.parse(await readFile(path.join(webRoot, 'package.json'), 'utf8')) as {
    dependencies?: Record<string, string>;
  };
  const dockerfiles = await Promise.all([
    readFile(path.join(webRoot, 'Dockerfile'), 'utf8'),
    readFile(path.join(webRoot, 'Dockerfile.prod'), 'utf8'),
  ]);

  assert.equal(packageJson.dependencies?.['@readium/navigator'], '2.8.2');
  assert.equal(packageJson.dependencies?.['@readium/shared'], '2.4.0');
  for (const dockerfile of dockerfiles) {
    assert.doesNotMatch(dockerfile, /third_party\/foliate-js/);
    assert.match(dockerfile, /pnpm install --frozen-lockfile --filter @shuku\/web\.\.\./);
  }
});
