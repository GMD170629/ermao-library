#!/usr/bin/env node

import { copyFile, mkdtemp, mkdir, readFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { spawn } from 'node:child_process';
import net from 'node:net';

const repoRoot = fileURLToPath(new URL('..', import.meta.url)).replace(/\/$/, '');
const apiRoot = join(repoRoot, 'apps', 'api-python');
const fixture = join(repoRoot, 'test-data', 'library', 'epub', 'reader-v2.epub');
const email = process.env.ACCEPTANCE_EMAIL ?? 'acceptance@example.com';
const password = process.env.ACCEPTANCE_PASSWORD ?? 'acceptance-password-123';

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => {
        if (!address || typeof address === 'string') {
          reject(new Error('failed to allocate an isolated TCP port'));
        } else {
          resolve(address.port);
        }
      });
    });
  });
}

function startProcess(command, args, env) {
  const child = spawn(command, args, {
    cwd: apiRoot,
    env,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  let output = '';
  child.stdout.on('data', (chunk) => {
    output += chunk.toString();
  });
  child.stderr.on('data', (chunk) => {
    output += chunk.toString();
  });
  child.output = () => output;
  return child;
}

function runPrestart(env) {
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
      else reject(new Error(`fresh schema bootstrap failed code=${code} signal=${signal}. Output: ${output}`));
    });
  });
}

async function waitForHealth(url, child) {
  const deadline = Date.now() + 20_000;
  let lastError = null;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error(`Python API exited before health check (code=${child.exitCode}, signal=${child.signalCode})`);
    }
    try {
      const response = await fetch(url);
      const payload = await response.json().catch(() => null);
      if (response.ok && payload?.ok === true && payload?.data?.status === 'ok') {
        return;
      }
      lastError = new Error(`unexpected health response ${response.status}: ${JSON.stringify(payload)}`);
    } catch (error) {
      lastError = error;
    }
    await sleep(250);
  }
  throw new Error(`isolated Python API did not become ready: ${lastError?.message ?? 'no response'}`);
}

async function waitForReady(readyFile, child) {
  const deadline = Date.now() + 20_000;
  let lastError = null;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error(`import worker exited before readiness (code=${child.exitCode}, signal=${child.signalCode})`);
    }
    try {
      const contents = (await readFile(readyFile, 'utf8')).trim();
      expect(/^\d+$/.test(contents), `worker readiness file contains an invalid pid: ${contents}`);
      return;
    } catch (error) {
      lastError = error;
    }
    await sleep(250);
  }
  throw new Error(`isolated import worker did not become ready: ${lastError?.message ?? 'ready file missing'}`);
}

async function stopProcess(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
  await Promise.race([
    new Promise((resolve) => child.once('exit', resolve)),
    sleep(5_000).then(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    })
  ]);
}

function cookieParts(headerValue) {
  if (!headerValue) return [];
  return headerValue.split(/,(?=[^;,=]+=[^;,]+)/g);
}

function updateCookieJar(jar, response) {
  const values = typeof response.headers.getSetCookie === 'function'
    ? response.headers.getSetCookie()
    : cookieParts(response.headers.get('set-cookie'));
  for (const value of values) {
    const pair = value.split(';', 1)[0];
    const separator = pair.indexOf('=');
    if (separator > 0) jar.set(pair.slice(0, separator), pair.slice(separator + 1));
  }
}

function pathFromUrl(value, baseUrl) {
  const parsed = new URL(value, baseUrl);
  expect(parsed.origin === new URL(baseUrl).origin, `asset URL escaped the isolated API: ${parsed}`);
  return `${parsed.pathname}${parsed.search}`;
}

async function main() {
  const tempDir = await mkdtemp(join(tmpdir(), 'shuku-acceptance-runtime-'));
  const storageRoot = join(tempDir, 'storage');
  const libraryRoot = join(tempDir, 'library');
  const inbox = join(tempDir, 'downloads', 'inbox');
  const readyFile = join(tempDir, 'import-worker-ready');
  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const env = {
    ...process.env,
    SESSION_SECRET: 'acceptance-runtime-session-secret-32chars',
    STORAGE_ROOT: storageRoot,
    DOWNLOAD_INBOX_PATH: inbox,
    IMPORT_WORKER_READY_FILE: readyFile,
    IMPORT_QUEUE_INTERVAL_SECONDS: '1'
  };
  let api;
  let worker;
  let migrationOutput = '';
  const cookieJar = new Map();

  async function request(path, init = {}) {
    const headers = new Headers(init.headers ?? {});
    if (cookieJar.size > 0) {
      headers.set(
        'cookie',
        [...cookieJar.entries()].map(([name, value]) => `${name}=${value}`).join('; ')
      );
    }
    const response = await fetch(`${baseUrl}${path}`, { ...init, headers });
    updateCookieJar(cookieJar, response);
    return response;
  }

  async function json(path, init) {
    const response = await request(path, init);
    const text = await response.text();
    let payload = null;
    try {
      payload = JSON.parse(text);
    } catch {
      // The assertion below reports the endpoint and status for non-JSON responses.
    }
    expect(
      response.ok && payload?.ok === true,
      `${path} failed with ${response.status}: ${text.slice(0, 500)}`
    );
    return payload.data;
  }

  try {
    await mkdir(libraryRoot, { recursive: true });
    await mkdir(storageRoot, { recursive: true });
    await mkdir(inbox, { recursive: true });
    await copyFile(fixture, join(libraryRoot, 'reader-v2.epub'));

    migrationOutput = await runPrestart(env);
    expect(migrationOutput.includes('prestart outcome=success'), 'fresh schema bootstrap did not complete');

    api = startProcess(
      'uv',
      [
        'run',
        '--extra',
        'dev',
        'uvicorn',
        'app.main:app',
        '--host',
        '127.0.0.1',
        '--port',
        String(port),
        '--log-level',
        'warning'
      ],
      env
    );
    await waitForHealth(`${baseUrl}/api/health`, api);

    worker = startProcess(
      'uv',
      ['run', '--extra', 'dev', 'python', '-m', 'app.worker.main'],
      env
    );
    await waitForReady(readyFile, worker);

    const setupStatus = await json('/api/auth/setup/status');
    expect(setupStatus.initialized === false, 'isolated database was unexpectedly initialized');
    await json('/api/auth/setup', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        name: 'Runtime Acceptance',
        email,
        password,
        locale: 'en-US'
      })
    });
    const session = await json('/api/auth/me');
    expect(session.user?.role === 'admin', 'setup did not create an administrator session');

    const libraryPayload = await json('/api/libraries', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        name: 'Runtime Acceptance Library',
        rootPath: libraryRoot,
        organizationMode: 'FLAT',
        enabled: true,
        ignoreHidden: true,
        minFileSizeBytes: 1
      })
    });
    const library = libraryPayload.library;
    expect(typeof library?.id === 'string' && library.organizationMode === 'FLAT', 'library contract is invalid');
    expect(library.rootPath === libraryRoot, 'library root path was not persisted as requested');

    let imported = null;
    let lastTaskState = null;
    const importDeadline = Date.now() + 45_000;
    while (Date.now() < importDeadline) {
      const tasksPayload = await json(
        `/api/libraries/${encodeURIComponent(library.id)}/import-tasks?pageSize=50`
      );
      const tasks = tasksPayload.tasks;
      lastTaskState = tasks.at(-1)?.state ?? null;
      const failedTask = tasks.find((task) => task.state === 'FAILED');
      expect(!failedTask, `worker import failed: ${failedTask?.errorSummary ?? failedTask?.id}`);

      const booksPayload = await json('/api/books?pageSize=5');
      const candidate = booksPayload.books.find((book) => book.libraryId === library.id);
      const pendingTask = tasks.some((task) => task.state === 'QUEUED' || task.state === 'RUNNING');
      if (candidate?.resources?.some((resource) => resource.assets.length > 0) && !pendingTask) {
        imported = candidate;
        break;
      }
      await sleep(250);
    }
    expect(imported, `worker did not publish a Book/ReadableResource/ResourceAsset topology in time (last task state: ${lastTaskState})`);

    const book = imported;
    expect(book.sourceNodeId, 'book is missing sourceNodeId');
    expect(book.resources.length > 0, 'book is missing readable resources');
    const resource = book.resources[0];
    expect(resource.bookId === book.id, 'readable resource is linked to a different book');
    expect(resource.sourceNodeId === book.sourceNodeId, 'readable resource is linked to a different source node');
    expect(resource.format === 'EPUB', `unexpected imported resource format: ${resource.format}`);
    expect(resource.assets.length > 0, 'readable resource is missing resource assets');
    const asset = resource.assets.find((item) => item.role === 'PRIMARY') ?? resource.assets[0];
    expect(asset.resourceId === resource.id, 'asset is linked to a different readable resource');
    expect(asset.sourceNodeId === resource.sourceNodeId, 'asset is linked to a different source node');
    expect(typeof asset.url === 'string' && typeof asset.downloadUrl === 'string', 'asset delivery URLs are missing');
    expect(!Object.hasOwn(asset, 'path') && !Object.hasOwn(asset, 'kind'), 'public asset contract leaked legacy storage fields');

    const detailPayload = await json(`/api/books/${encodeURIComponent(book.id)}`);
    expect(detailPayload.book.id === book.id, 'book detail did not return the imported book');
    const resourcesPayload = await json(`/api/books/${encodeURIComponent(book.id)}/resources?pageSize=50`);
    expect(resourcesPayload.resources.some((item) => item.id === resource.id), 'book resource listing omitted imported resource');
    const resourcePayload = await json(`/api/resources/${encodeURIComponent(resource.id)}`);
    expect(resourcePayload.resource.id === resource.id, 'resource detail did not return imported resource');
    const assetsPayload = await json(`/api/resources/${encodeURIComponent(resource.id)}/assets?pageSize=500`);
    expect(assetsPayload.assets.some((item) => item.id === asset.id), 'resource asset listing omitted imported asset');
    const contentsPayload = await json(`/api/books/${encodeURIComponent(book.id)}/contents?pageSize=50`);
    expect(
      contentsPayload.bookId === book.id &&
        contentsPayload.currentNode.sourceNodeId === book.sourceNodeId &&
        contentsPayload.currentResourceId === resource.id,
      'book contents did not resolve the source-node topology'
    );

    const librariesPayload = await json('/api/libraries');
    expect(librariesPayload.libraries.some((item) => item.id === library.id), 'library listing omitted the isolated library');
    const facetsPayload = await json('/api/library/facets?kind=AUTHOR&pageSize=20');
    expect(Array.isArray(facetsPayload.facets), 'facet endpoint did not return facets');
    const groupingsPayload = await json('/api/library/groupings?kind=SERIES&pageSize=20');
    expect(Array.isArray(groupingsPayload.groups), 'grouping endpoint did not return groups');
    const filterSchemaPayload = await json('/api/library/filter-schema');
    expect(Array.isArray(filterSchemaPayload.fields), 'filter schema endpoint did not return fields');
    const filterOptionsPayload = await json('/api/library/filter-options?source=authors&limit=5');
    expect(Array.isArray(filterOptionsPayload.options), 'filter options endpoint did not return options');
    const dashboardPayload = await json('/api/dashboard/recent-books?limit=5');
    expect(Array.isArray(dashboardPayload.books), 'dashboard endpoint did not return books');
    await json('/api/dashboard/recent-reading?limit=5');
    await json('/api/dashboard/continue-reading');

    const downloadPath = pathFromUrl(asset.downloadUrl, baseUrl);
    const download = await request(downloadPath);
    expect(download.ok, `asset delivery failed with ${download.status}`);
    expect(
      download.headers.get('content-type')?.startsWith(asset.mimeType),
      `asset delivery returned an unexpected MIME type: ${download.headers.get('content-type') ?? 'missing'} (asset=${asset.mimeType})`
    );
    const delivered = new Uint8Array(await download.arrayBuffer());
    expect(delivered.length > 0, 'asset delivery returned an empty payload');
    const attachment = await request(`${downloadPath}${downloadPath.includes('?') ? '&' : '?'}download=true`);
    expect(attachment.ok, `asset attachment delivery failed with ${attachment.status}`);
    expect(attachment.headers.get('content-disposition')?.toLowerCase().includes('attachment'), 'download=true did not request an attachment');

    console.log(`[acceptance] isolated runtime passed: library=${library.id} sourceNode=${book.sourceNodeId} book=${book.id} resource=${resource.id} asset=${asset.id} port=${port}`);
  } finally {
    await stopProcess(worker);
    await stopProcess(api);
    await rm(tempDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
