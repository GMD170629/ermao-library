import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('standalone production image supports optimization under the configured runtime user', async () => {
  const [packageSource, dockerfile, launcher] = await Promise.all([
    readFile('package.json', 'utf8'),
    readFile('Dockerfile.prod', 'utf8'),
    readFile('../../scripts/container-entry.py', 'utf8')
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
    /mkdir -p [^\n]*\/opt\/shuku-image\/apps\/web\/\.next\/cache/
  );
  assert.match(launcher, /shutil\.copytree\(seed, runtime, symlinks=True\)/);
  assert.match(launcher, /runtime \/ "apps\/web\/\.next\/cache"/);
  assert.match(launcher, /with tempfile\.TemporaryFile\(dir=directory\):/);
  assert.doesNotMatch(launcher, /os\.(?:chmod|chown)\(/);
});
