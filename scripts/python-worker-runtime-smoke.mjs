#!/usr/bin/env node
import { access, mkdtemp, readFile, rm } from 'node:fs/promises';
import { constants } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';

const repoRoot = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const apiRoot = join(repoRoot, 'apps/api-python');

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

function waitForExit(child, timeoutMs = 5000) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve({ code: child.exitCode, signal: child.signalCode });
  }
  return Promise.race([
    new Promise((resolve) => child.once('exit', (code, signal) => resolve({ code, signal }))),
    sleep(timeoutMs).then(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
      return new Promise((resolve) => child.once('exit', (code, signal) => resolve({ code, signal })));
    })
  ]);
}

async function waitForReady(readyFile, child) {
  const deadline = Date.now() + 15000;
  let lastError = null;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`worker exited early with code ${child.exitCode}`);
    }
    try {
      await access(readyFile, constants.R_OK);
      return (await readFile(readyFile, 'utf8')).trim();
    } catch (error) {
      lastError = error;
    }
    await sleep(250);
  }
  throw new Error(`Python worker runtime smoke timed out: ${lastError?.message ?? 'ready file not created'}`);
}

async function main() {
  const tempDir = await mkdtemp(join(tmpdir(), 'shuku-python-worker-smoke-'));
  const monitorRoot = join(tempDir, 'monitor');
  const storageRoot = join(tempDir, 'storage');
  const inbox = join(tempDir, 'downloads/inbox');
  const readyFile = join(tempDir, 'scan-worker-ready');
  const env = {
    ...process.env,
    SESSION_SECRET: 'runtime-smoke-session-secret-32chars',
    STORAGE_ROOT: storageRoot,
    DOWNLOAD_INBOX_PATH: inbox,
    IMPORT_WORKER_READY_FILE: readyFile,
    IMPORT_QUEUE_INTERVAL_SECONDS: '1'
  };

  let child;
  let runtimeOutput = '';
  try {
    const { mkdir } = await import('node:fs/promises');
    await Promise.all([
      mkdir(monitorRoot, { recursive: true }),
      mkdir(storageRoot, { recursive: true }),
      mkdir(inbox, { recursive: true })
    ]);

    const migrationOutput = await runStartupDataMigrations(env);
    child = spawn('uv', ['run', '--extra', 'dev', 'python', '-m', 'app.worker.main'], {
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

    const pidText = await waitForReady(readyFile, child);
    if (!/^\d+$/.test(pidText)) {
      throw new Error(`ready file did not contain a process id: ${pidText}`);
    }
    if (!migrationOutput.includes('prestart outcome=success')) {
      throw new Error(`prestart did not report success. Output: ${migrationOutput}`);
    }
    if (!runtimeOutput.includes('schema_barrier outcome=ready')) {
      throw new Error(`worker did not verify the current schema. Output: ${runtimeOutput}`);
    }
    child.kill('SIGTERM');
    const exit = await waitForExit(child);
    if (exit.code !== 0 && exit.signal !== 'SIGTERM') {
      throw new Error(`worker stopped unexpectedly with code=${exit.code} signal=${exit.signal}. Output: ${runtimeOutput}`);
    }
    try {
      await access(readyFile, constants.F_OK);
      throw new Error('ready file still exists after worker shutdown');
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }

    console.log('Python worker runtime smoke ok');
    const output = `${migrationOutput}${runtimeOutput}`;
    const interesting = output
      .split(/\r?\n/)
      .filter((line) =>
        line.includes('data_migration') ||
        line.includes('readable_resource.worker.ready') ||
        line.includes('unavailable') ||
        line.includes('retrying later') ||
        line.includes('signal')
      )
      .join('\n')
      .trim();
    if (interesting) console.log(interesting);
  } finally {
    if (child && child.exitCode === null && child.signalCode === null) {
      child.kill('SIGTERM');
      await waitForExit(child);
    }
    await rm(tempDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
