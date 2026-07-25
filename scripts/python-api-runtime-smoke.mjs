#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import { access, mkdir, mkdtemp, rm } from 'node:fs/promises';
import net from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const repoRoot = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const apiRoot = join(repoRoot, 'apps/api-python');

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => {
        if (!address || typeof address === 'string') reject(new Error('failed to allocate a TCP port'));
        else resolve(address.port);
      });
    });
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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

async function waitForHealth(url, processRef) {
  const deadline = Date.now() + 20000;
  let lastError = null;
  while (Date.now() < deadline) {
    if (processRef.exitCode !== null) {
      throw new Error(`appv2 uvicorn exited early with code ${processRef.exitCode}`);
    }
    try {
      const response = await fetch(url, { headers: { 'Accept-Language': 'en-US' } });
      const payload = await response.json();
      if (response.ok && payload?.status === 'healthy' && payload?.version === '0.4.0') {
        return payload;
      }
      lastError = new Error(`unexpected health response ${response.status}: ${JSON.stringify(payload)}`);
    } catch (error) {
      lastError = error;
    }
    await sleep(250);
  }
  throw new Error(`appv2 API runtime smoke timed out: ${lastError?.message ?? 'no response'}`);
}

async function main() {
  const databaseUrl = process.env.APPV2_TEST_DATABASE_URL ?? process.env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error('APPV2_TEST_DATABASE_URL or DATABASE_URL must point to an isolated PostgreSQL 18 database');
  }

  const tempDir = await mkdtemp(join(tmpdir(), 'shuku-appv2-api-smoke-'));
  const port = await freePort();
  const monitorRoot = join(tempDir, 'monitor');
  const storageRoot = join(tempDir, 'storage');
  const env = {
    ...process.env,
    DATABASE_URL: databaseUrl,
    SESSION_SECRET: 'runtime-smoke-session-secret-at-least-32-characters',
    MONITOR_ROOT: monitorRoot,
    STORAGE_ROOT: storageRoot,
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

    child = spawn(
      'uv',
      [
        'run',
        'uvicorn',
        'appv2.entrypoints.api:app',
        '--host',
        '127.0.0.1',
        '--port',
        String(port),
        '--log-level',
        'warning'
      ],
      { cwd: apiRoot, env, stdio: ['ignore', 'pipe', 'pipe'] }
    );
    child.stdout.on('data', (chunk) => {
      output += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      output += chunk.toString();
    });

    const health = await waitForHealth(`http://127.0.0.1:${port}/api/v2/operations/health`, child);
    const contributorNames = new Set(health.contributors.map((item) => item.name));
    for (const expected of ['database', 'storage']) {
      if (!contributorNames.has(expected)) throw new Error(`health response missing ${expected} contributor`);
    }

    const openapiResponse = await fetch(`http://127.0.0.1:${port}/openapi.json`);
    const openapi = await openapiResponse.json();
    if (!openapiResponse.ok || openapi.info?.version !== '0.4.0') {
      throw new Error(`unexpected OpenAPI metadata: ${JSON.stringify(openapi.info)}`);
    }
    const paths = Object.keys(openapi.paths ?? {});
    if (!paths.length || paths.some((path) => !path.startsWith('/api/v2/'))) {
      throw new Error(`OpenAPI exposed a non-v2 route: ${paths.join(', ')}`);
    }

    try {
      await access(join(storageRoot, 'database/shuku.sqlite3'));
      throw new Error('appv2 created or touched the legacy SQLite database');
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
    console.log(`appv2 API runtime smoke ok on port ${port}`);
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
