import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

const image = `example/app@sha256:${'a'.repeat(64)}`;
const manifest = (architecture, digit) => ({
  platform: { os: 'linux', architecture }, digest: `sha256:${digit.repeat(64)}`
});

function run(t, manifests) {
  const root = mkdtempSync(path.join(tmpdir(), 'ermao-package-platform-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(path.join(root, 'bin'));
  const calls = path.join(root, 'calls.jsonl');
  writeFileSync(calls, '');
  writeFileSync(path.join(root, 'bin/docker'), `#!/usr/bin/env node
const fs = require('node:fs');
const args = process.argv.slice(2);
fs.appendFileSync(process.env.PACKAGE_TEST_CALLS, JSON.stringify(args) + '\\n');
if (args[0] === 'buildx') {
  process.stdout.write(process.env.PACKAGE_TEST_INDEX);
} else if (args[0] === 'run') {
  if (args.includes('linux/arm64')) process.exit(73);
  const output = args.find(value => value.endsWith(':/packages')).slice(0, -10);
  fs.writeFileSync(output + '/fixture-code.tar.gz.json', '{}');
} else process.exit(74);
`, { mode: 0o755 });
  const result = spawnSync('bash', ['scripts/build-release-app-packages.sh', image, path.join(root, 'output')], {
    encoding: 'utf8',
    env: { ...process.env, PATH: `${path.join(root, 'bin')}:${process.env.PATH}`,
      PACKAGE_TEST_CALLS: calls, PACKAGE_TEST_INDEX: JSON.stringify({ manifests }) }
  });
  return { result, calls: readFileSync(calls, 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line)) };
}

test('each architecture uses its own immutable child digest, excluding attestations', t => {
  const { result, calls } = run(t, [manifest('amd64', 'b'), manifest('arm64', 'c'), {
    ...manifest('amd64', 'd'), annotations: { 'vnd.docker.reference.type': 'attestation-manifest' }
  }]);
  // The fake container fails on arm64, so the script must stop before merging incomplete outputs.
  assert.equal(result.status, 73, result.stderr);
  assert.deepEqual(calls[0], ['buildx', 'imagetools', 'inspect', image, '--raw']);
  const containers = calls.filter(args => args[0] === 'run');
  assert.equal(containers.length, 2);
  for (const [index, architecture, digit] of [[0, 'amd64', 'b'], [1, 'arm64', 'c']]) {
    assert.ok(containers[index].includes(`linux/${architecture}`));
    assert.ok(containers[index].includes(`example/app@sha256:${digit.repeat(64)}`));
    assert.ok(!containers[index].includes(image));
  }
});

test('missing, ambiguous or malformed architecture digests never start a container', t => {
  for (const manifests of [[], [manifest('amd64', 'b'), manifest('amd64', 'c')], [
    { ...manifest('amd64', 'b'), digest: 'latest' }
  ]]) {
    const { result, calls } = run(t, manifests);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Expected one immutable linux\/amd64 image manifest/);
    assert.equal(calls.filter(args => args[0] === 'run').length, 0);
  }
});
