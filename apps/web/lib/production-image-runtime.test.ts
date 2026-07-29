import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('standalone production image supports optimization under the configured runtime user', async () => {
  const [packageSource, dockerfile] = await Promise.all([
    readFile('package.json', 'utf8'),
    readFile('Dockerfile.prod', 'utf8')
  ]);
  const packageManifest = JSON.parse(packageSource) as {
    dependencies?: Record<string, string>;
  };

  assert.ok(
    packageManifest.dependencies?.sharp,
    'sharp must be a production dependency so Next.js includes it in standalone output'
  );
  assert.match(
    dockerfile,
    /mkdir -p [^\n]*\/app\/apps\/web\/\.next\/cache/
  );
  assert.match(
    dockerfile,
    /chmod 1777 \/app\/apps\/web\/\.next\/cache/
  );
});
