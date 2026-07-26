#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const repoRoot = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const apiRoot = join(repoRoot, 'apps/api-python');

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForStarted(child, outputRef) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`appv2 worker exited early with code ${child.exitCode}: ${outputRef()}`);
    }
    if (outputRef().includes('appv2 worker started')) return;
    await sleep(200);
  }
  throw new Error(`appv2 worker did not report readiness: ${outputRef()}`);
}

async function stop(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.kill('SIGTERM');
  await Promise.race([
    new Promise((resolve) => child.once('exit', resolve)),
    sleep(5000).then(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    })
  ]);
}

async function main() {
  const databaseUrl = process.env.APPV2_TEST_DATABASE_URL ?? process.env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error('APPV2_TEST_DATABASE_URL or DATABASE_URL must point to an isolated PostgreSQL 18 database');
  }
  const tempDir = await mkdtemp(join(tmpdir(), 'shuku-appv2-worker-smoke-'));
  const monitorRoot = join(tempDir, 'monitor');
  const storageRoot = join(tempDir, 'storage');
  const env = {
    ...process.env,
    DATABASE_URL: databaseUrl,
    SESSION_SECRET: 'runtime-smoke-session-secret-at-least-32-characters',
    MONITOR_ROOT: monitorRoot,
    STORAGE_ROOT: storageRoot,
    WORKER_POLL_SECONDS: '0.1',
    ENVIRONMENT: 'test'
  };
  let child;
  let output = '';
  try {
    await Promise.all([mkdir(monitorRoot, { recursive: true }), mkdir(storageRoot, { recursive: true })]);
    const migration = spawnSync('uv', ['run', 'python', '-m', 'appv2.entrypoints.migrate'], {
      cwd: apiRoot,
      env,
      encoding: 'utf8'
    });
    if (migration.status !== 0) {
      throw new Error(`appv2 migration failed:\n${migration.stdout ?? ''}\n${migration.stderr ?? ''}`);
    }
    child = spawn('uv', ['run', 'python', '-m', 'appv2.entrypoints.worker'], {
      cwd: apiRoot,
      env,
      stdio: ['ignore', 'pipe', 'pipe']
    });
    child.stdout.on('data', (chunk) => {
      output += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      output += chunk.toString();
    });
    await waitForStarted(child, () => output);
    await sleep(500);
    if (child.exitCode !== null) throw new Error(`appv2 worker stopped unexpectedly: ${output}`);
    console.log('appv2 worker runtime smoke ok');
  } finally {
    await stop(child);
    if (output.trim()) console.log(output.trim());
    await rm(tempDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
