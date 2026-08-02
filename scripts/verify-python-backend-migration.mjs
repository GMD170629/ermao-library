#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const repoRoot = new URL('..', import.meta.url).pathname.replace(/\/$/, '');

function run(command, args, options = {}) {
  console.log(`\n$ ${command} ${args.join(' ')}`);
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? repoRoot,
    stdio: options.stdio ?? 'inherit',
    shell: false,
    env: options.env ?? process.env
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function runQuiet(command, args, options = {}) {
  console.log(`\n$ ${command} ${args.join(' ')}`);
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? repoRoot,
    encoding: 'utf8',
    shell: false,
    env: options.env ?? process.env
  });
  if (result.status !== 0) {
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }
  console.log(options.successMessage ?? 'ok');
}

function capture(command, args, options = {}) {
  console.log(`\n$ ${command} ${args.join(' ')}`);
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? repoRoot,
    encoding: 'utf8',
    shell: false,
    env: options.env ?? process.env
  });
  if (result.status !== 0) {
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }
  return result.stdout;
}

function expectIncludes(file, snippet) {
  const path = join(repoRoot, file);
  const text = readFileSync(path, 'utf8');
  if (!text.includes(snippet)) {
    throw new Error(`${file} is missing expected snippet: ${snippet}`);
  }
}

function expectNotIncludes(file, snippet) {
  const path = join(repoRoot, file);
  const text = readFileSync(path, 'utf8');
  if (text.includes(snippet)) {
    throw new Error(`${file} still contains legacy snippet: ${snippet}`);
  }
}

function expectServices(label, output, expectedPresent, expectedAbsent = []) {
  const services = new Set(output.split(/\r?\n/).map((line) => line.trim()).filter(Boolean));
  for (const service of expectedPresent) {
    if (!services.has(service)) {
      throw new Error(`${label} is missing expected service: ${service}. Services: ${[...services].join(', ')}`);
    }
  }
  for (const service of expectedAbsent) {
    if (services.has(service)) {
      throw new Error(`${label} unexpectedly includes service: ${service}. Services: ${[...services].join(', ')}`);
    }
  }
  const unexpected = [...services].filter((service) => !expectedPresent.includes(service));
  if (unexpected.length > 0) {
    throw new Error(`${label} includes unexpected services: ${unexpected.join(', ')}`);
  }
  console.log(`${label} services ok: ${[...services].join(', ')}`);
}

run('uv', ['run', '--extra', 'dev', 'python', '-m', 'compileall', 'app', 'tests', '-q'], {
  cwd: join(repoRoot, 'apps/api-python')
});
run('uv', ['run', '--extra', 'dev', 'pytest', '-q'], {
  cwd: join(repoRoot, 'apps/api-python')
});
run('node', ['scripts/python-api-runtime-smoke.mjs']);
run('node', ['scripts/python-worker-runtime-smoke.mjs']);
run('uv', ['run', '--extra', 'dev', 'python', '../../scripts/python_worker_import_smoke.py'], {
  cwd: join(repoRoot, 'apps/api-python')
});
run('uv', ['run', '--extra', 'dev', 'python', '../../scripts/python_backend_sample_smoke.py'], {
  cwd: join(repoRoot, 'apps/api-python')
});
run('pnpm', ['--filter', '@shuku/web', 'typecheck']);
run('pnpm', ['--filter', '@shuku/web', 'test', '--', '--test-reporter=spec']);
const composeEnv = { ...process.env };
runQuiet('docker', ['compose', '-f', 'docker-compose.yml', 'config'], { successMessage: 'dev compose config ok', env: composeEnv });
runQuiet('docker', ['compose', '-f', 'docker-compose.prod.yml', 'config'], { successMessage: 'prod compose config ok', env: composeEnv });
expectServices(
  'dev unified topology',
  capture('docker', ['compose', '-f', 'docker-compose.yml', 'config', '--services'], { env: composeEnv }),
  ['manga-downloader', 'web'],
  ['migrate', 'api-python', 'scan-worker-python', 'scan-worker']
);
expectServices(
  'prod unified topology',
  capture('docker', ['compose', '-f', 'docker-compose.prod.yml', 'config', '--services'], { env: composeEnv }),
  ['web'],
  ['migrate', 'api-python', 'scan-worker-python', 'scan-worker']
);
run('bash', ['-n', 'scripts/publish-docker-hub.sh']);
run('sh', ['-n', 'scripts/start-unified-app.sh']);

expectIncludes('apps/web/next.config.js', 'beforeFiles');
expectIncludes('apps/web/next.config.js', 'http://127.0.0.1:8000');
expectIncludes('scripts/dev-test.sh', 'uv run --extra dev uvicorn app.main:app');
expectIncludes('scripts/dev-test.sh', 'uv run --extra dev python -m app.worker.main');
expectNotIncludes('scripts/dev-test.sh', 'pnpm --filter @shuku/scan-worker dev');
expectIncludes('apps/web/Dockerfile.prod', 'scripts/start-unified-app.sh');
expectIncludes('apps/web/Dockerfile.prod', 'pip install --no-cache-dir ./apps/api-python');
expectIncludes('apps/web/Dockerfile.prod', 'apps/api-python/app');
expectIncludes('apps/web/Dockerfile.prod', 'libmobi-tools');
expectNotIncludes('apps/web/Dockerfile.prod', 'calibre');
expectNotIncludes('apps/web/Dockerfile.prod', 'AS migrator');
expectNotIncludes('docker-compose.yml', 'API_PYTHON_PORT');
expectNotIncludes('docker-compose.prod.yml', 'API_PYTHON_PORT');
expectNotIncludes('docker-compose.yml', 'MONITOR_ROOT');
expectNotIncludes('docker-compose.prod.yml', 'MONITOR_ROOT');
expectIncludes('docker-compose.yml', '${STORAGE_PATH:-./data/storage}:/app/storage');
expectIncludes('docker-compose.prod.yml', '${STORAGE_PATH:-./data/storage}:/app/storage');
expectIncludes('docker-compose.yml', '${MONITOR_HOST_PATH:-./monitor}:/monitor');
expectIncludes('docker-compose.prod.yml', '${MONITOR_HOST_PATH:-./monitor}:/monitor');
expectIncludes('docker-compose.yml', '/path/to/another-library:/libraries/another');
expectIncludes('docker-compose.prod.yml', '/path/to/another-library:/libraries/another');
expectIncludes('docker-compose.prod.yml', 'scripts/start-unified-app.sh');
expectNotIncludes('docker-compose.yml', 'ADMIN_EMAIL');
expectNotIncludes('docker-compose.yml', 'ADMIN_PASSWORD');
expectNotIncludes('docker-compose.prod.yml', 'ADMIN_EMAIL');
expectNotIncludes('docker-compose.prod.yml', 'ADMIN_PASSWORD');
expectIncludes('deploy/fnos/app/docker/docker-compose.yaml', '${TRIM_PKGVAR}/storage:/app/storage');
expectIncludes('deploy/fnos/app/docker/docker-compose.yaml', '${TRIM_DATA_SHARE_PATHS}:/monitor');
expectIncludes('deploy/fnos/app/docker/docker-compose.yaml', 'STORAGE_ROOT: /app/storage');
expectNotIncludes('deploy/fnos/app/docker/docker-compose.yaml', 'MONITOR_ROOT');
expectNotIncludes('deploy/fnos/app/docker/docker-compose.yaml', 'ADMIN_EMAIL');
expectNotIncludes('deploy/fnos/app/docker/docker-compose.yaml', 'ADMIN_PASSWORD');
expectNotIncludes('docker-compose.yml', 'profiles:');
expectNotIncludes('docker-compose.yml', 'api-python:');
expectNotIncludes('docker-compose.yml', 'scan-worker-python:');
expectNotIncludes('docker-compose.yml', 'scan-worker:');
expectNotIncludes('docker-compose.prod.yml', 'profiles:');
expectNotIncludes('docker-compose.prod.yml', 'api-python:');
expectNotIncludes('docker-compose.prod.yml', 'scan-worker-python:');
expectNotIncludes('docker-compose.prod.yml', 'scan-worker:');
expectNotIncludes('scripts/publish-docker-hub.sh', 'shuku-starship-api-python');
expectNotIncludes('scripts/publish-docker-hub.sh', 'shuku-starship-scan-worker');
expectNotIncludes('scripts/publish-docker-hub.sh', 'shuku-starship-migrator');
expectNotIncludes('apps/web/next.config.js', 'PYTHON_API_PROXY_TARGET');

if (process.env.VERIFY_DOCKER_BUILD === 'true') {
  run('docker', ['build', '-f', 'apps/web/Dockerfile.prod', '--target', 'runner', '-t', 'shuku-starship-unified:verify', '.']);
} else {
  console.log('\nSkipping Docker image build. Set VERIFY_DOCKER_BUILD=true to include it.');
}

console.log('\nPython backend migration verification completed.');
