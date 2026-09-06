import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const sourceCommit = '1234567890abcdef1234567890abcdef12345678';

function fixture(t) {
  const root = mkdtempSync(path.join(tmpdir(), 'ermao-oci-test-'));
  t.after(() => {
    assert.equal(path.dirname(path.resolve(root)), path.resolve(tmpdir()));
    assert.ok(path.basename(root).startsWith('ermao-oci-test-'));
    rmSync(root, { recursive: true, force: true });
  });
  mkdirSync(path.join(root, 'scripts'));
  mkdirSync(path.join(root, 'bin'));
  copyFileSync('scripts/publish-docker-hub.sh', path.join(root, 'scripts/publish-docker-hub.sh'));
  writeFileSync(path.join(root, 'package.json'), JSON.stringify({ version: '1.0.0' }));
  const commands = {
    git: `printf 'git %s\\n' "$*" >> calls.log
case "$1" in
  status) printf '%s' "\${FAKE_DIRTY:-}"; if [ -e .source-dirty ]; then printf ' M generated'; fi ;;
  rev-parse) printf '${sourceCommit}\\n' ;;
  archive) printf 'test-only source archive' ;;
  *) exit 91 ;;
esac`,
    pnpm: `printf 'pnpm %s\\n' "$*" >> calls.log
if [ "\${FAKE_DIRTY_AFTER_CHECKS:-}" = true ] && [[ "$*" == *'web build' ]]; then touch .source-dirty; fi`,
    docker: `printf 'docker %s\\n' "$*" >> calls.log
if [ "$1" = buildx ] && [ "$2" = build ]; then
  if [ "\${!#}" = - ]; then cat >/dev/null; fi
  if [ "\${FAKE_BUILD_FAILURE:-}" = true ]; then exit 73; fi
  for arg in "$@"; do
    case "$arg" in
      type=oci,dest=*) printf 'test-only OCI stub' > "\${arg#type=oci,dest=}" ;;
    esac
  done
fi`,
  };
  for (const [name, content] of Object.entries(commands)) {
    const filename = path.join(root, 'bin', name);
    writeFileSync(filename, `#!/usr/bin/env bash\nset -euo pipefail\n${content}\n`);
    chmodSync(filename, 0o755);
  }
  return {
    root,
    run(args, extraEnv = {}) {
      // Git Bash prepends its own Git directory at startup. Set the test-only
      // command boundary inside Bash so every Docker/Git call uses these stubs.
      const result = spawnSync('bash', ['-c', 'export PATH="$PWD/bin:$PATH"; exec bash scripts/publish-docker-hub.sh "$@"', 'oci-test', ...args], {
        cwd: root,
        env: { ...process.env, PATH: `${path.join(root, 'bin')}${path.delimiter}${process.env.PATH}`, ...extraEnv },
        encoding: 'utf8', timeout: 30_000,
      });
      assert.equal(result.error, undefined, result.error?.message);
      return result;
    },
    calls() { return readFileSync(path.join(root, 'calls.log'), 'utf8'); },
  };
}

test('local export never pushes and records the exact artifact hash and source', (t) => {
  const f = fixture(t);
  const result = f.run(['--output-dir', 'local artifacts', '--skip-checks']);
  assert.equal(result.status, 0, result.stderr);
  assert.doesNotMatch(f.calls(), /--push|docker login|docker tag/u);
  assert.doesNotMatch(f.calls(), /-t docker.io\/gamersgu|:prod/u);
  assert.match(f.calls(), /pnpm release:validate/u);
  assert.match(f.calls(), /--platform linux\/amd64,linux\/arm64/u);
  assert.match(f.calls(), /--target runner/u);
  assert.match(f.calls(), new RegExp('git archive --format=tar ' + sourceCommit, 'u'));
  assert.match(f.calls(), /--label org.opencontainers.image.revision=1234567890abcdef/u);
  const directory = path.join(f.root, 'local artifacts');
  const archive = readdirSync(directory).find((name) => name.endsWith('.oci.tar'));
  assert.ok(archive);
  const bytes = readFileSync(path.join(directory, archive));
  const manifest = JSON.parse(readFileSync(path.join(directory, `${archive}.json`), 'utf8'));
  assert.deepEqual(manifest, {
    archive, sha256: createHash('sha256').update(bytes).digest('hex'), sourceCommit,
    version: '1.0.0', image: `ermao-local/shuku-starship-web:${sourceCommit}`,
    platforms: ['linux/amd64', 'linux/arm64'], published: false,
  });
  const repeat = f.run(['--output-dir', 'local artifacts', '--skip-checks']);
  assert.notEqual(repeat.status, 0);
  assert.match(repeat.stderr, /Refusing to overwrite/u);
  assert.deepEqual(readFileSync(path.join(directory, archive)), bytes);
});

test('dirty RC source cannot reach a build or create an artifact', (t) => {
  const f = fixture(t);
  const result = f.run(['--output-dir', 'artifacts', '--skip-checks'], { FAKE_DIRTY: ' M app.py' });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /clean committed source/u);
  assert.doesNotMatch(f.calls(), /docker buildx build/u);
  assert.equal(existsSync(path.join(f.root, 'artifacts')), false);
});

test('explicit publisher mode retains its original checks and push behavior', (t) => {
  const f = fixture(t);
  const result = f.run([]);
  assert.equal(result.status, 0, result.stderr);
  assert.match(f.calls(), /docker buildx build .*--push/u);
  assert.match(f.calls(), /pnpm --filter @shuku\/web test/u);
  assert.doesNotMatch(f.calls(), /type=oci/u);
});

test('checks that change source invalidate the local RC before Docker build', (t) => {
  const f = fixture(t);
  const result = f.run(['--output-dir', 'artifacts'], { FAKE_DIRTY_AFTER_CHECKS: 'true' });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /clean committed source/u);
  assert.doesNotMatch(f.calls(), /docker buildx build/u);
});

test('failed OCI build never writes a success manifest or falls back to push', (t) => {
  const f = fixture(t);
  const result = f.run(['--output-dir', 'artifacts', '--skip-checks'], { FAKE_BUILD_FAILURE: 'true' });
  assert.equal(result.status, 73);
  assert.doesNotMatch(f.calls(), /--push/u);
  assert.deepEqual(readdirSync(path.join(f.root, 'artifacts')), []);
});
