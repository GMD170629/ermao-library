#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const repoRoot = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const apiRoot = join(repoRoot, 'apps/api-python');

function run(command, args, options = {}) {
  console.log(`\n$ ${command} ${args.join(' ')}`);
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? repoRoot,
    stdio: 'inherit',
    shell: false,
    env: options.env ?? process.env
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function read(path) {
  return readFileSync(join(repoRoot, path), 'utf8');
}

function expectIncludes(path, expected) {
  if (!read(path).includes(expected)) {
    throw new Error(`${path} does not contain ${JSON.stringify(expected)}`);
  }
}

function expectExcludes(path, forbidden) {
  if (read(path).includes(forbidden)) {
    throw new Error(`${path} still contains forbidden legacy reference ${JSON.stringify(forbidden)}`);
  }
}

function versionFromToml(source, key) {
  const match = source.match(new RegExp(`^${key} = "([^"]+)"`, 'm'));
  if (!match) throw new Error(`could not read ${key} from TOML`);
  return match[1];
}

const rootVersion = JSON.parse(read('package.json')).version;
const webVersion = JSON.parse(read('apps/web/package.json')).version;
const pythonVersion = versionFromToml(read('apps/api-python/pyproject.toml'), 'version');
const runtimeMatch = read('apps/api-python/appv2/platform/config/settings.py').match(
  /^\s*app_version: str = "([^"]+)"/m
);
const lockMatch = read('apps/api-python/uv.lock').match(
  /name = "shuku-starship-api-python"\nversion = "([^"]+)"/
);
const versions = { rootVersion, webVersion, pythonVersion, runtimeVersion: runtimeMatch?.[1], lockVersion: lockMatch?.[1] };
if (Object.values(versions).some((version) => version !== '0.4.0')) {
  throw new Error(`v0.4.0 version consistency failed: ${JSON.stringify(versions)}`);
}

expectIncludes('apps/api-python/pyproject.toml', 'include = ["appv2*"]');
expectIncludes('apps/api-python/Dockerfile', 'appv2.entrypoints.api:app');
expectIncludes('apps/web/Dockerfile.prod', 'appv2.entrypoints.api:app');
expectIncludes('scripts/start-unified-app.sh', 'appv2.entrypoints.worker');
expectIncludes('scripts/dev-test.sh', 'appv2.entrypoints.worker');
expectIncludes('docker-compose.yml', 'postgres:18.4-alpine3.23');
expectIncludes('docker-compose.prod.yml', 'postgres:18.4-alpine3.23');
expectIncludes('docker-compose.yml', 'PGDATA: /var/lib/postgresql/18/docker');
expectIncludes('deploy/fnos/app/docker/docker-compose.yaml', 'postgres:18.4-alpine3.23');
expectIncludes('docker-compose.external-db.yml', 'DATABASE_URL');
expectExcludes('apps/api-python/Dockerfile', 'COPY apps/api-python/app ');
expectExcludes('apps/web/Dockerfile.prod', 'COPY apps/api-python/app ');
expectExcludes('scripts/start-unified-app.sh', 'app.main:app');
expectExcludes('scripts/dev-test.sh', 'app.main:app');
expectExcludes('docker-compose.yml', 'shuku.sqlite3');
expectExcludes('docker-compose.prod.yml', 'shuku.sqlite3');

run('uv', ['run', 'ruff', 'format', '--check', 'appv2', 'tests'], { cwd: apiRoot });
run('uv', ['run', 'ruff', 'check', 'appv2', 'tests'], { cwd: apiRoot });
run('uv', ['run', 'mypy', 'appv2'], { cwd: apiRoot });
run('uv', ['run', 'pytest', '-q'], { cwd: apiRoot });
run('uv', ['run', 'alembic', '-c', 'alembic-v2.ini', 'upgrade', 'head', '--sql'], {
  cwd: apiRoot
});

if (process.env.APPV2_TEST_DATABASE_URL || process.env.DATABASE_URL) {
  run('node', ['scripts/python-api-runtime-smoke.mjs']);
  run('node', ['scripts/python-worker-runtime-smoke.mjs']);
  run('uv', ['run', 'python', '../../scripts/python_worker_import_smoke.py'], { cwd: apiRoot });
  run('uv', ['run', 'python', '../../scripts/python_backend_sample_smoke.py'], { cwd: apiRoot });
} else {
  console.log('\nSkipping PostgreSQL runtime smokes; set APPV2_TEST_DATABASE_URL to an isolated PostgreSQL 18 database.');
}

if (process.env.VERIFY_DOCKER_BUILD === 'true') {
  run('docker', [
    'build',
    '-f',
    'apps/web/Dockerfile.prod',
    '--target',
    'runner',
    '-t',
    'shuku-starship-appv2:verify',
    '.'
  ]);
} else {
  console.log('\nSkipping Docker image build. Set VERIFY_DOCKER_BUILD=true to include it.');
}

console.log('\nappv2 backend migration verification completed.');
