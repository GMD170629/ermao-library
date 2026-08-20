#!/usr/bin/env node
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import net from 'node:net';

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

function runStartupDataMigrations(env) {
  return new Promise((resolve, reject) => {
    const migration = spawn(
      'uv',
      ['run', '--extra', 'dev', 'python', '-m', 'app.bootstrap.prestart'],
      {
        cwd: apiRoot,
        env,
        stdio: ['ignore', 'pipe', 'pipe']
      }
    );
    let output = '';
    migration.stdout.on('data', (chunk) => {
      output += chunk.toString();
    });
    migration.stderr.on('data', (chunk) => {
      output += chunk.toString();
    });
    migration.once('error', reject);
    migration.once('exit', (code, signal) => {
      if (code === 0) resolve(output);
      else reject(new Error(`startup migrations failed code=${code} signal=${signal}. Output: ${output}`));
    });
  });
}

async function waitForHealth(url, processRef) {
  const deadline = Date.now() + 15000;
  let lastError = null;
  while (Date.now() < deadline) {
    if (processRef.exitCode !== null) {
      throw new Error(`uvicorn exited early with code ${processRef.exitCode}`);
    }
    try {
      const response = await fetch(url);
      const payload = await response.json();
      if (response.ok && payload?.ok === true && payload?.data?.status === 'ok') {
        return payload;
      }
      lastError = new Error(`unexpected health response ${response.status}: ${JSON.stringify(payload)}`);
    } catch (error) {
      lastError = error;
    }
    await sleep(250);
  }
  throw new Error(`Python API runtime smoke timed out: ${lastError?.message ?? 'no response'}`);
}

async function main() {
  const tempDir = await mkdtemp(join(tmpdir(), 'shuku-python-api-smoke-'));
  const port = await freePort();
  const monitorRoot = join(tempDir, 'monitor');
  const storageRoot = join(tempDir, 'storage');
  const inbox = join(tempDir, 'downloads/inbox');
  const env = {
    ...process.env,
    SESSION_SECRET: 'runtime-smoke-session-secret-32chars',
    STORAGE_ROOT: storageRoot,
    DOWNLOAD_INBOX_PATH: inbox
  };

  let child;
  try {
    await Promise.all([
      import('node:fs/promises').then(({ mkdir }) => mkdir(monitorRoot, { recursive: true })),
      import('node:fs/promises').then(({ mkdir }) => mkdir(storageRoot, { recursive: true })),
      import('node:fs/promises').then(({ mkdir }) => mkdir(inbox, { recursive: true }))
    ]);

    const migrationOutput = await runStartupDataMigrations(env);
    let runtimeOutput = '';
    child = spawn('uv', ['run', '--extra', 'dev', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning'], {
      cwd: apiRoot,
      env,
      stdio: ['ignore', 'pipe', 'pipe']
    });
    child.stdout.on('data', (chunk) => {
      runtimeOutput += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      runtimeOutput += chunk.toString();
    });

    const health = await waitForHealth(`http://127.0.0.1:${port}/api/health`, child);
    if (health?.data?.service !== 'ermao-books' || !['ok', 'error'].includes(health?.data?.status)) {
      throw new Error('/api/health returned an invalid public health envelope');
    }
    const ping = await fetch(`http://127.0.0.1:${port}/api/__db-ping`);
    if (!ping.ok) throw new Error(`/api/__db-ping returned ${ping.status}`);
    await import('node:fs/promises').then(({ access }) => access(join(storageRoot, 'database/shuku.sqlite3')));
    if (!migrationOutput.includes('prestart outcome=success')) {
      throw new Error(`prestart did not report success. Output: ${migrationOutput}`);
    }
    if (!runtimeOutput.includes('schema_barrier outcome=ready')) {
      throw new Error(`API did not verify the current schema. Output: ${runtimeOutput}`);
    }
    console.log(`Python API runtime smoke ok on port ${port}`);
    const output = `${migrationOutput}${runtimeOutput}`;
    if (output.trim()) console.log(output.trim());
  } finally {
    if (child && child.exitCode === null) {
      child.kill('SIGTERM');
      await Promise.race([
        new Promise((resolve) => child.once('exit', resolve)),
        sleep(5000).then(() => {
          if (child.exitCode === null) child.kill('SIGKILL');
        })
      ]);
    }
    await rm(tempDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
