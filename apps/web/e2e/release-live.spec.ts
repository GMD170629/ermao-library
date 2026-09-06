import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, resolve } from 'node:path';
import { execFile, spawn, type ChildProcess } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { promisify } from 'node:util';

import { expect, test, type BrowserContext, type Page, type Request, type Response } from '@playwright/test';
import timingFixture from '../../../packages/reader-contracts/fixtures/reader-progress-timing-v1.json';
import { READER_V5_DB_NAME, readerV5ProgressKey } from '../lib/reader/v5-storage';
import { parseReaderV5ProgressPut, parseReaderV5ProgressSnapshot, parseReaderV5ProgressWriteResult } from '../lib/reader/v5-wire';
import { revealReaderControls, visibleReaderFrame } from './reader-controls';
import { audioSoakSeconds, observeAudioSoak, startAudioProbe } from './release-audio-soak';

type JsonRecord = Record<string, unknown>;

type LiveSample = {
  format: string;
  kind?: string;
  sourcePath: string;
  fixturePath: string;
  sourceExtension?: string;
  expectedMime?: string;
  corpusManifest?: string;
  durationClaim?: string;
  sourceSha256?: string;
  fixtureSha256: string;
  sizeBytes: number;
};

type LiveManifest = {
  runId: string;
  repoHead: string;
  apiOrigin: string;
  webOrigin: string;
  artifactDir: string;
  databasePath: string;
  libraryRootPath: string;
  libraryName: string;
  organizationMode: string;
  audioCorpusRoot?: string;
  audioCorpusManifest?: string;
  ffprobeAvailable: boolean;
  ffprobePath?: string;
  email: string;
  samples: LiveSample[];
  processLogs: JsonRecord;
};

type FixtureRun = {
  child: ChildProcess;
  artifactDir: string;
  manifestPath: string;
  stopFile: string;
  shutdownFile: string;
  manifest: LiveManifest | null;
  spawnError: Error | null;
};

type ApiResponseObservation = {
  method: string;
  path: string;
  status: number;
};

type CatalogEntry = {
  bookId: string;
  bookTitle: string;
  resourceId: string;
  resourceTitle: string;
  format: string;
  readerType: string;
  assetMimeTypes: string[];
};

type ProgressWriteObservation = {
  path: string;
  body: unknown;
};

const REPO_ROOT = resolve(__dirname, '../../..');
const DEFAULT_ARTIFACT_ROOT = resolve(
  REPO_ROOT,
  'artifacts/releases/1.0/197e81a808ba32595a8a6ffeda62422b3a7d3473/release-live'
);
const RESERVED_PORTS = new Set([3000, 3100, 8000]);
const productionWeb = process.env.RELEASE_LIVE_WEB_RUNTIME === 'production';
// Includes preflight, bounded prepare/build/readiness, then the existing
// browser/soak budget and enough time for LoggedProcess tree shutdown.
const FIXTURE_STARTUP_TIMEOUT_MS = 1_200_000;
const FIXTURE_STOP_TIMEOUT_MS = 120_000;

function record(value: unknown): JsonRecord {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('expected JSON object');
  }
  return value as JsonRecord;
}

function optionalRecord(value: unknown): JsonRecord | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  return value as JsonRecord;
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new Error(`missing ${field}`);
  return value;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function numberValue(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`missing ${field}`);
  return value;
}

function recordArray(value: unknown, field: string): JsonRecord[] {
  if (!Array.isArray(value)) throw new Error(`missing ${field}`);
  return value.map((item) => record(item));
}

function parseManifest(value: unknown): LiveManifest {
  const root = record(value);
  const sampleValues = recordArray(root.samples, 'samples');
  return {
    runId: stringValue(root.runId, 'runId'),
    repoHead: stringValue(root.repoHead, 'repoHead'),
    apiOrigin: stringValue(root.apiOrigin, 'apiOrigin'),
    webOrigin: stringValue(root.webOrigin, 'webOrigin'),
    artifactDir: stringValue(root.artifactDir, 'artifactDir'),
    databasePath: stringValue(root.databasePath, 'databasePath'),
    libraryRootPath: stringValue(root.libraryRootPath, 'libraryRootPath'),
    libraryName: stringValue(root.libraryName, 'libraryName'),
    organizationMode: stringValue(root.organizationMode, 'organizationMode'),
    audioCorpusRoot: optionalString(root.audioCorpusRoot),
    audioCorpusManifest: optionalString(root.audioCorpusManifest),
    ffprobeAvailable: root.ffprobeAvailable === true,
    ffprobePath: optionalString(root.ffprobePath),
    email: stringValue(root.email, 'email'),
    processLogs: record(root.processLogs),
    samples: sampleValues.map((sample) => ({
      format: stringValue(sample.format, 'sample.format'),
      kind: optionalString(sample.kind),
      sourcePath: stringValue(sample.sourcePath, 'sample.sourcePath'),
      fixturePath: stringValue(sample.fixturePath, 'sample.fixturePath'),
      sourceExtension: optionalString(sample.sourceExtension),
      expectedMime: optionalString(sample.expectedMime),
      corpusManifest: optionalString(sample.corpusManifest),
      durationClaim: optionalString(sample.durationClaim),
      sourceSha256: optionalString(sample.sourceSha256),
      fixtureSha256: stringValue(sample.fixtureSha256, 'sample.fixtureSha256'),
      sizeBytes: numberValue(sample.sizeBytes, 'sample.sizeBytes')
    }))
  };
}

function redact(value: string, secret: string): string {
  return secret.length > 0 ? value.split(secret).join('[REDACTED]') : value;
}

async function readJson(path: string): Promise<unknown> {
  return JSON.parse(await readFile(path, 'utf8')) as unknown;
}

function safeFixtureError(error: unknown): Error {
  const password = process.env.RELEASE_LIVE_PASSWORD ?? '';
  if (error instanceof AggregateError) {
    const errors: unknown[] = error.errors;
    return new AggregateError(errors.map(safeFixtureError), redact(error.message, password));
  }
  const safe = new Error(redact(error instanceof Error ? error.message : String(error), password));
  if (error instanceof Error) {
    safe.name = error.name;
    if (error.stack) safe.stack = redact(error.stack, password);
  }
  return safe;
}

function combineFixtureErrors(primary: Error | null, cleanup: Error | null): Error | null {
  if (primary && cleanup) {
    return new AggregateError([primary, cleanup], `${primary.message}\nFixture cleanup also failed: ${cleanup.message}`);
  }
  return primary ?? cleanup;
}

async function stopFixture(fixture: FixtureRun): Promise<string | null> {
  await writeFile(fixture.stopFile, 'stop\n', 'utf8');
  const deadline = Date.now() + FIXTURE_STOP_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (fixture.spawnError && fixture.child.pid === undefined) return null;
    if (fixture.child.exitCode !== null || fixture.child.signalCode !== null) {
      const resultPath = resolve(fixture.artifactDir, 'shutdown-result.json');
      if (!existsSync(resultPath)) {
        throw new Error(`fixture exited without a shutdown result; inspect ${fixture.artifactDir}`);
      }
      const result = record(await readJson(resultPath));
      const cleanupErrors = result.cleanupErrors;
      if (!Array.isArray(cleanupErrors) || !cleanupErrors.every((entry) => typeof entry === 'string')) {
        throw new Error(`invalid fixture cleanup result; inspect ${resultPath}`);
      }
      if (result.status !== 'stopped' || result.processesStopped !== true || cleanupErrors.length > 0 || !existsSync(fixture.shutdownFile)) {
        throw new Error(`fixture cleanup failed: ${cleanupErrors.join('; ') || 'shutdown not confirmed'}; inspect ${resultPath}`);
      }
      if (typeof result.primaryError === 'string') return result.primaryError;
      if (result.primaryError !== null) throw new Error(`invalid fixture primary error; inspect ${resultPath}`);
      return fixture.child.exitCode === 0 ? null : `fixture exited ${fixture.child.exitCode ?? fixture.child.signalCode}`;
    }
    await delay(100);
  }
  const childState = fixture.child.exitCode === null ? 'still running' : `exited ${fixture.child.exitCode}`;
  throw new Error(`fixture did not confirm Python LoggedProcess shutdown (${childState}); inspect ${fixture.shutdownFile}`);
}

async function startFixture(testInfo: { workerIndex: number }): Promise<FixtureRun> {
  const configuredBaseURL = process.env.PLAYWRIGHT_BASE_URL;
  if (!configuredBaseURL) {
    throw new Error('RELEASE_LIVE_E2E=1 requires PLAYWRIGHT_BASE_URL for the isolated Next server');
  }
  const webURL = new URL(configuredBaseURL);
  if (!['127.0.0.1', 'localhost', '::1', ...(productionWeb ? ['release-live.localhost'] : [])].includes(webURL.hostname)) {
    throw new Error('release live E2E requires a loopback PLAYWRIGHT_BASE_URL');
  }
  const webPort = Number(webURL.port || (webURL.protocol === 'https:' ? 443 : 80));
  if (RESERVED_PORTS.has(webPort)) throw new Error(`PLAYWRIGHT_BASE_URL uses reserved port ${webPort}`);

  const apiPort = Number(process.env.RELEASE_LIVE_API_PORT ?? '18080');
  if (!Number.isInteger(apiPort) || RESERVED_PORTS.has(apiPort)) {
    throw new Error(`RELEASE_LIVE_API_PORT must be an isolated integer port: ${apiPort}`);
  }
  const runId = `r${Date.now()}-w${testInfo.workerIndex}`;
  const artifactRoot = resolve(process.env.RELEASE_LIVE_ARTIFACT_ROOT ?? DEFAULT_ARTIFACT_ROOT);
  const artifactDir = resolve(artifactRoot, runId);
  const manifestPath = resolve(artifactDir, 'manifest.json');
  const stopFile = resolve(artifactDir, 'stop');
  const shutdownFile = resolve(artifactDir, 'shutdown-complete');
  await mkdir(artifactDir, { recursive: true });

  const python = process.env.RELEASE_LIVE_PYTHON;
  if (!python) throw new Error('Set RELEASE_LIVE_PYTHON to the isolated Python executable');
  if (!existsSync(python)) throw new Error(`release live Python runtime not found: ${python}`);
  const script = resolve(REPO_ROOT, 'scripts/python_release_live_fixture.py');
  const child = spawn(
    python,
    [
      script,
      '--artifact-dir', artifactDir,
      '--manifest', manifestPath,
      '--stop-file', stopFile,
      '--shutdown-file', shutdownFile,
      '--run-id', runId,
      '--api-port', String(apiPort),
      '--web-port', String(webPort),
      '--web-runtime', productionWeb ? 'production' : 'development',
      '--lifetime-seconds', String(audioSoakSeconds() + 600),
      '--startup-timeout-seconds', String(FIXTURE_STARTUP_TIMEOUT_MS / 1_000),
      ...(productionWeb ? ['--web-hostname', 'release-live.localhost'] : [])
    ],
    {
      cwd: REPO_ROOT,
      env: { ...process.env, RELEASE_LIVE_E2E: '1' },
      stdio: ['ignore', 'ignore', 'ignore']
    }
  );
  const provisional: FixtureRun = {
    child,
    artifactDir,
    manifestPath,
    stopFile,
    shutdownFile,
    manifest: null,
    spawnError: null
  };
  child.once('error', (error) => { provisional.spawnError = error; });
  const deadline = Date.now() + FIXTURE_STARTUP_TIMEOUT_MS;
  try {
    while (Date.now() < deadline) {
      if (provisional.spawnError) throw provisional.spawnError;
      if (child.exitCode !== null || child.signalCode !== null) {
        const fixtureLog = resolve(artifactDir, 'fixture.log');
        const detail = existsSync(fixtureLog) ? await readFile(fixtureLog, 'utf8') : 'fixture.log missing';
        throw new Error(`live fixture exited before readiness (${child.exitCode})\n${detail}`);
      }
      if (existsSync(manifestPath)) {
        const manifest = parseManifest(await readJson(manifestPath));
        provisional.manifest = manifest;
        return provisional;
      }
      await delay(500);
    }
    throw new Error(`live fixture readiness timed out; inspect ${resolve(artifactDir, 'fixture.log')}`);
  } catch (error) {
    const primary = safeFixtureError(error);
    let cleanup: Error | null = null;
    try {
      await stopFixture(provisional);
    } catch (cleanupError) {
      cleanup = safeFixtureError(cleanupError);
    }
    try {
      await writeFile(resolve(artifactDir, 'startup-failure.json'), `${JSON.stringify({
        failure: primary.message,
        cleanupFailure: cleanup?.message ?? null,
        exitCode: child.exitCode,
        signal: child.signalCode
      }, null, 2)}\n`, 'utf8');
    } catch (evidenceError) {
      cleanup = combineFixtureErrors(cleanup, safeFixtureError(evidenceError));
    }
    throw combineFixtureErrors(primary, cleanup);
  }
}

async function requestJson(
  page: Page,
  origin: string,
  path: string,
  observations: ApiResponseObservation[],
  method = 'GET',
  data?: JsonRecord
): Promise<{ status: number; payload: unknown }> {
  const response = await page.evaluate(async ({ origin, path, method, data }) => {
    if (origin !== location.origin) throw new Error('Live verification requires the current isolated origin');
    const result = await fetch(`${origin}${path}`, {
      method,
      cache: 'no-store',
      credentials: 'same-origin',
      ...(data === undefined ? {} : {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
    });
    return { status: result.status, text: await result.text() };
  }, { origin, path, method, data });
  const text = response.text;
  let payload: unknown = null;
  try {
    payload = JSON.parse(text) as unknown;
  } catch {
    payload = text;
  }
  observations.push({ method, path, status: response.status });
  return { status: response.status, payload };
}

function responseData(result: { status: number; payload: unknown }, path: string): JsonRecord {
  if (result.status < 200 || result.status >= 300) {
    throw new Error(`${path} returned HTTP ${result.status}`);
  }
  const envelope = record(result.payload);
  if (envelope.ok !== true) throw new Error(`${path} returned a failed envelope`);
  return record(envelope.data);
}

async function waitForCatalog(
  page: Page,
  origin: string,
  observations: ApiResponseObservation[],
  requiredAudioCount: number
): Promise<CatalogEntry[]> {
  const deadline = Date.now() + 150_000;
  let lastError = 'catalog is still empty';
  while (Date.now() < deadline) {
    try {
      const catalog = responseData(
        await requestJson(page, origin, '/api/books?pageSize=100', observations),
        '/api/books'
      );
      const entries: CatalogEntry[] = [];
      for (const book of recordArray(catalog.books, 'books')) {
        const bookId = stringValue(book.id, 'book.id');
        const detail = responseData(
          await requestJson(page, origin, `/api/books/${encodeURIComponent(bookId)}`, observations),
          `/api/books/${bookId}`
        );
        const detailBook = record(detail.book);
        for (const resource of recordArray(detailBook.resources, 'book.resources')) {
          entries.push({
            bookId,
            bookTitle: stringValue(detailBook.title, 'book.title'),
            resourceId: stringValue(resource.id, 'resource.id'),
            resourceTitle: stringValue(resource.title, 'resource.title'),
            format: stringValue(resource.format, 'resource.format').toUpperCase(),
            readerType: stringValue(resource.readerType, 'resource.readerType'),
            assetMimeTypes: recordArray(resource.assets, 'resource.assets').map(
              (asset) => stringValue(asset.mimeType, 'asset.mimeType')
            )
          });
        }
      }
      const formats = new Set(entries.map((entry) => entry.format));
      const audioEntries = entries.filter((entry) => entry.readerType === 'audio');
      if (
        formats.has('EPUB')
        && formats.has('PDF')
        && formats.has('CBZ')
        && audioEntries.length >= requiredAudioCount
      ) return entries;
      lastError = `formats=${Array.from(formats).join(',') || 'none'} audio=${audioEntries.length}/${requiredAudioCount} entries=${entries.length}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await delay(750);
  }
  throw new Error(`catalog did not contain EPUB/PDF/CBZ and the required audio resources: ${lastError}`);
}

async function waitForImportTasks(
  page: Page,
  origin: string,
  libraryId: string,
  observations: ApiResponseObservation[],
  failures: JsonRecord[]
): Promise<void> {
  const path = `/api/libraries/${encodeURIComponent(libraryId)}/import-tasks?pageSize=100`;
  const deadline = Date.now() + 150_000;
  let lastState = 'no task response';
  while (Date.now() < deadline) {
    const result = await requestJson(page, origin, path, observations);
    if (result.status >= 200 && result.status < 300) {
      const data = responseData(result, path);
      const tasks = recordArray(data.tasks, 'tasks');
      const failed = tasks.filter((task) => task.state === 'FAILED');
      if (failed.length > 0) {
        failures.push(...failed);
        throw new Error(`import task failed: ${JSON.stringify(failed)}`);
      }
      lastState = tasks.map((task) => String(task.state)).join(',') || 'empty';
      if (tasks.length > 0 && tasks.every((task) => task.state === 'SUCCEEDED')) return;
    } else {
      lastState = `HTTP ${result.status}`;
    }
    await delay(750);
  }
  throw new Error(`import tasks did not settle: ${lastState}`);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function openDetailResource(page: Page, action: '打开阅读器' | '打开播放器'): Promise<void> {
  const open = page.getByRole('button', { name: action, exact: true }).first();
  const resources = page.getByRole('button', { name: /^可读资源 1/ }).first();
  await expect(open.or(resources).first()).toBeVisible();
  if (!await open.isVisible()) await resources.click();
  await expect(open).toBeVisible();
  await open.click();
}

async function setupLiveCatalog(
  page: Page,
  manifest: LiveManifest,
  password: string,
  apiResponses: ApiResponseObservation[],
  importTaskFailures: JsonRecord[],
  screenshots: string[]
): Promise<{ catalog: CatalogEntry[]; epub: CatalogEntry }> {
  const { webOrigin } = manifest;
  if (!manifest.ffprobeAvailable) throw new Error('Live audio import verification requires the configured ffprobe tool');
  const requiredAudioCount = 4;
  const samplesByFormat = new Map(manifest.samples.map((sample) => [sample.format.toUpperCase(), sample]));
  expect(samplesByFormat.get('EPUB')?.fixtureSha256).toBeTruthy();
  expect(samplesByFormat.get('PDF')?.fixtureSha256).toBeTruthy();
  expect(samplesByFormat.get('CBZ')?.fixtureSha256).toBeTruthy();
  for (const [format, extension] of [
    ['AUDIO_MP3', '.mp3'],
    ['AUDIO_AAC', '.aac'],
    ['AUDIO_WAV', '.wav'],
    ['AUDIO_FLAC', '.flac']
  ] as const) {
    const sample = samplesByFormat.get(format);
    expect(sample?.fixtureSha256, `${format} fixture hash`).toBeTruthy();
    expect(sample?.sourceExtension, `${format} source extension`).toBe(extension);
    expect(sample?.corpusManifest, `${format} corpus manifest`).toBeTruthy();
    expect(sample?.durationClaim).toContain('duration must be verified by the actual engine');
  }
  await mkdir(resolve(manifest.artifactDir, 'screenshots'), { recursive: true });

  await page.goto(`${webOrigin}/setup`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: '创建你的管理账户' })).toBeVisible();
  if (productionWeb) {
    expect(new URL(webOrigin).hostname, 'production PWA must exercise the caching branch').toBe('release-live.localhost');
    expect(await page.evaluate(() => window.isSecureContext)).toBe(true);
    await page.waitForFunction(() => navigator.serviceWorker.controller?.state === 'activated');
  }
  const setupForm = page.getByTestId('setup-form');
  const setupInputs = setupForm.locator('input');
  await setupInputs.nth(0).fill('Release Live Admin');
  await setupInputs.nth(1).fill(manifest.email);
  await setupInputs.nth(2).fill(password);
  await setupInputs.nth(3).fill(password);
  await page.getByRole('button', { name: '创建账户', exact: true }).click();
  await expect(page.getByRole('heading', { name: '添加书库' })).toBeVisible();
  await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/01-setup-account.png') });
  screenshots.push('screenshots/01-setup-account.png');

  const libraryRegion = page.getByRole('region', { name: '书库清单' });
  await libraryRegion.getByRole('button', { name: /添加书库/ }).click();
  const dialog = page.getByRole('dialog', { name: '新增书库' });
  await expect(dialog).toBeVisible();
  await page.getByLabel('书库名称').fill(manifest.libraryName);
  await page.getByRole('combobox', { name: '书库路径' }).fill(manifest.libraryRootPath);
  const collapseTree = dialog.getByRole('button', { name: '收起文件夹路径树' });
  if (await collapseTree.count() > 0) await collapseTree.click();
  await dialog.getByRole('radio', { name: '单本' }).click();
  await dialog.getByRole('button', { name: '添加', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(manifest.libraryName, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '确认', exact: true }).click();
  await expect(page).toHaveURL(/\/library$/);

  const librariesResult = await requestJson(page, webOrigin, '/api/libraries', apiResponses);
  const librariesData = responseData(librariesResult, '/api/libraries');
  const libraries = recordArray(librariesData.libraries, 'libraries');
  const library = libraries.find((candidate) => candidate.name === manifest.libraryName);
  if (!library) throw new Error('created FLAT library was not returned by the real API');
  const libraryId = stringValue(library.id, 'library.id');
  expect(library.organizationMode).toBe('FLAT');
  expect(library.enabled).toBe(true);

  const scanPath = `/api/libraries/${encodeURIComponent(libraryId)}/scan`;
  const scanResult = await requestJson(page, webOrigin, scanPath, apiResponses, 'POST');
  expect(scanResult.status).toBe(202);
  await waitForImportTasks(
    page,
    webOrigin,
    libraryId,
    apiResponses,
    importTaskFailures
  );
  const catalog = await waitForCatalog(page, webOrigin, apiResponses, requiredAudioCount);
  const epub = catalog.find((entry) => entry.format === 'EPUB');
  if (!epub) throw new Error('real catalog did not contain an EPUB resource');
  expect(catalog.some((entry) => entry.format === 'PDF')).toBe(true);
  expect(catalog.some((entry) => entry.format === 'CBZ')).toBe(true);
  const audioEntries = catalog.filter((entry) => entry.readerType === 'audio');
  expect(audioEntries.length).toBeGreaterThanOrEqual(requiredAudioCount);
  expect(importTaskFailures).toHaveLength(0);
  await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/02-library-imported.png') });
  screenshots.push('screenshots/02-library-imported.png');

  const logout = await requestJson(page, webOrigin, '/api/auth/logout', apiResponses, 'POST');
  expect(logout.status).toBe(200);
  await page.context().clearCookies();
  await page.goto(`${webOrigin}/login`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible();
  const loginInputs = page.locator('form input');
  await loginInputs.nth(0).fill(manifest.email);
  await loginInputs.nth(1).fill(password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/library$/);

  const expectedBookCount = new Set(catalog.map((entry) => entry.bookId)).size;
  const libraryBookButtons = page.getByRole('button', { name: /查看《/ });
  await expect.poll(() => libraryBookButtons.count()).toBeGreaterThanOrEqual(expectedBookCount);
  for (const catalogEntry of catalog) {
    await expect(
      page.getByRole('button', { name: new RegExp(escapeRegExp(catalogEntry.bookTitle)) }).first()
    ).toBeVisible();
  }
  await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/03-library-list-after-login.png') });
  screenshots.push('screenshots/03-library-list-after-login.png');
  return { catalog, epub };
}

const requestedAudioMime = process.env.RELEASE_LIVE_AUDIO_MIME ?? 'audio/mpeg';

function livePassword(): string {
  const password = process.env.RELEASE_LIVE_PASSWORD;
  if (!password || password.length < 10) throw new Error('RELEASE_LIVE_PASSWORD must be a local-only password of at least 10 characters');
  return password;
}

async function openLiveAudioPlayer(page: Page) {
  await openDetailResource(page, '打开播放器');
  const player = page.getByTestId('audio-mini-player');
  await expect(player).toBeVisible({ timeout: 30_000 });
  const audioToggle = player.getByTestId('audio-play-toggle');
  await expect(audioToggle).toBeVisible({ timeout: 30_000 });
  if (await audioToggle.getAttribute('aria-label') === '播放') await audioToggle.click();
  await expect(audioToggle).toHaveAttribute('aria-label', '暂停', { timeout: 30_000 });
  return { player, audioToggle };
}

// Observe both stores in one completed readonly transaction. Opening a
// missing DB aborts its upgrade instead of creating test progress/schema.
const storedProgress = (target: Page) => target.evaluate(async (databaseName) => {
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const open = indexedDB.open(databaseName);
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
    open.onupgradeneeded = () => { open.transaction?.abort(); reject(new Error('v5 database must already exist')); };
  });
  try {
    return await new Promise<{ pending: unknown[]; exact: unknown[] }>((resolve, reject) => {
      const transaction = database.transaction(['pending-position', 'position'], 'readonly');
      const pending = transaction.objectStore('pending-position').getAll();
      const exact = transaction.objectStore('position').getAll();
      transaction.oncomplete = () => resolve({ pending: pending.result, exact: exact.result });
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally { database.close(); }
}, READER_V5_DB_NAME);

type ChromeProcessIdentity = { pid: number; createdAt: string; executablePath: string; commandLine: string };

async function readChromeProcess(pid: number): Promise<ChromeProcessIdentity | null> {
  if (!Number.isSafeInteger(pid) || pid <= 0) throw new Error('invalid dedicated Chrome PID');
  const { stdout } = await promisify(execFile)('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', `
    $ErrorActionPreference = 'Stop'
    $chromeProcess = Get-CimInstance Win32_Process -Filter "ProcessId = ${pid}"
    if ($null -ne $chromeProcess) {
      @{ pid = [int]$chromeProcess.ProcessId; createdAt = $chromeProcess.CreationDate.ToUniversalTime().ToString('o'); executablePath = $chromeProcess.ExecutablePath; commandLine = $chromeProcess.CommandLine } | ConvertTo-Json -Compress
    }
  `], { windowsHide: true, timeout: 10_000, maxBuffer: 65_536 });
  if (!stdout.trim()) return null;
  const value = record(JSON.parse(stdout));
  return {
    pid: numberValue(value.pid, 'Chrome PID'),
    createdAt: stringValue(value.createdAt, 'Chrome creation time'),
    executablePath: stringValue(value.executablePath, 'Chrome executable'),
    commandLine: stringValue(value.commandLine, 'Chrome command line')
  };
}

async function identifyDedicatedChrome(context: BrowserContext, profile: string, launchStartedAt: number) {
  const browser = context.browser();
  if (!browser) throw new Error('dedicated desktop Chrome browser is unavailable');
  const cdp = await browser.newBrowserCDPSession();
  try {
    const processes = await cdp.send('SystemInfo.getProcessInfo');
    const roots = processes.processInfo.filter((entry) => entry.type === 'browser');
    expect(roots).toHaveLength(1);
    const command = await cdp.send('Browser.getBrowserCommandLine');
    expect(command.arguments.filter((arg) => arg.startsWith('--user-data-dir=')))
      .toEqual([`--user-data-dir=${profile}`]);
    const root = await readChromeProcess(roots[0].id);
    if (!root) throw new Error('dedicated Chrome root exited before ownership verification');
    expect(root.pid).toBe(roots[0].id);
    expect(basename(root.executablePath).toLowerCase()).toBe('chrome.exe');
    expect(Date.parse(root.createdAt)).toBeGreaterThanOrEqual(launchStartedAt);
    expect(Date.parse(root.createdAt)).toBeLessThanOrEqual(Date.now());
    // Check the exact argument, not a profile-name substring or a parent path.
    const path = escapeRegExp(profile);
    expect(root.commandLine).toMatch(new RegExp(`(?:^|\\s)(?:"--user-data-dir=${path}"|--user-data-dir="${path}"|--user-data-dir=${path})(?=\\s|$)`, 'i'));
    return root;
  } finally { await cdp.detach(); }
}

test('release live paused confirmed MP3 survives dedicated Chrome process termination', async ({ playwright }, testInfo) => {
  test.setTimeout(FIXTURE_STARTUP_TIMEOUT_MS + 300_000 + FIXTURE_STOP_TIMEOUT_MS);
  if (!productionWeb || process.platform !== 'win32') {
    throw new Error('RG04_POS03 requires production Chrome on Windows for CDP/CIM process ownership');
  }
  const password = livePassword();
  const apiResponses: ApiResponseObservation[] = [];
  const importTaskFailures: JsonRecord[] = [];
  const screenshots: string[] = [];
  const evidence: JsonRecord = { gate: 'RG04/POS03', scenario: 'paused-confirmed-process-kill', phase: 'setup' };
  const contexts: BrowserContext[] = [];
  const roots: ChromeProcessIdentity[] = [];
  const cleanup: JsonRecord[] = [];
  const progressRequests: Request[] = [];
  const progressResponses: Response[] = [];
  let progressPath: string | null = null;
  let fixture: FixtureRun | null = null;
  let manifest: LiveManifest | null = null;
  let profile: string | null = null;
  let primaryFailure: Error | null = null;
  let cleanupFailure: Error | null = null;

  const launch = async (profilePath: string) => {
    const startedAt = Date.now();
    const { viewport, deviceScaleFactor, isMobile, hasTouch, userAgent } = testInfo.project.use;
    const context = await playwright.chromium.launchPersistentContext(profilePath, {
      channel: 'chrome', headless: true, serviceWorkers: 'allow',
      viewport, deviceScaleFactor, isMobile, hasTouch, userAgent
    });
    contexts.push(context);
    context.on('request', (request) => {
      const url = new URL(request.url());
      if (url.origin === manifest?.webOrigin && url.pathname === progressPath && request.method() === 'PUT') {
        progressRequests.push(request);
      }
    });
    context.on('response', (response) => {
      const url = new URL(response.url());
      if (url.origin !== manifest?.webOrigin || !url.pathname.startsWith('/api/')) return;
      const method = response.request().method();
      apiResponses.push({ method, path: `${url.pathname}${url.search}`, status: response.status() });
      if (method === 'PUT' && url.pathname === progressPath) progressResponses.push(response);
    });
    const root = await identifyDedicatedChrome(context, profilePath, startedAt);
    roots.push(root);
    return { context, root, startedAt };
  };

  try {
    fixture = await startFixture(testInfo);
    manifest = fixture.manifest;
    if (!manifest) throw new Error('live fixture returned without a manifest');
    const { webOrigin } = manifest;
    const temporaryRoot = resolve(REPO_ROOT, '.tmp');
    await mkdir(temporaryRoot, { recursive: true });
    // No caller-supplied profile, user profile or junction out of the workspace.
    expect((await realpath(temporaryRoot)).toLowerCase()).toBe(temporaryRoot.toLowerCase());
    profile = await mkdtemp(resolve(temporaryRoot, 'rg04-pos03-chrome-'));
    expect(await realpath(profile)).toBe(profile);
    evidence.profile = profile;
    const source = await launch(profile);
    const page = source.context.pages()[0] ?? await source.context.newPage();
    const { catalog } = await setupLiveCatalog(page, manifest, password, apiResponses, importTaskFailures, screenshots);
    const audio = catalog.find((entry) => entry.readerType === 'audio' && entry.assetMimeTypes.includes('audio/mpeg'));
    if (!audio) throw new Error('real catalog did not contain the required MP3 resource');
    expect(manifest.samples.some((sample) => sample.expectedMime === 'audio/mpeg')).toBe(true);
    progressPath = `/api/reader/v5/resources/${encodeURIComponent(audio.resourceId)}/progress`;
    expect(responseData(await requestJson(page, webOrigin, progressPath, apiResponses), progressPath).progressSnapshot).toBeNull();
    const detailURL = `${webOrigin}/books/${encodeURIComponent(audio.bookId)}?resourceId=${encodeURIComponent(audio.resourceId)}`;
    await page.goto(detailURL, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(audio.bookTitle, { exact: true }).first()).toBeVisible();
    const { audioToggle } = await openLiveAudioPlayer(page);
    const engine = page.locator('audio');
    const startedPosition = await engine.evaluate((element: HTMLAudioElement) => element.currentTime * 1_000);
    await expect.poll(() => engine.evaluate((element: HTMLAudioElement) => element.currentTime * 1_000), { timeout: 15_000 })
      .toBeGreaterThanOrEqual(startedPosition + 5_000);
    const pauseRequestedAt = Date.now();
    await audioToggle.click();
    await expect(audioToggle).toHaveAttribute('aria-label', '播放');
    const paused = await engine.evaluate((element: HTMLAudioElement) => ({ paused: element.paused, positionMillis: element.currentTime * 1_000 }));
    expect(paused.paused).toBe(true);
    expect(paused.positionMillis).toBeGreaterThanOrEqual(startedPosition + 5_000);
    evidence.phase = 'confirm-paused';
    await expect.poll(() => {
      const latest = progressRequests.at(-1);
      const upload = latest && parseReaderV5ProgressPut(latest.postDataJSON());
      return Boolean(upload && upload.capturedAtEpochMillis >= pauseRequestedAt
        && progressResponses.some((response) => response.request() === latest));
    }).toBe(true);
    const latestRequest = progressRequests.at(-1);
    const ackResponse = progressResponses.filter((response) => response.request() === latestRequest).at(-1);
    if (!latestRequest || !ackResponse) throw new Error('RG04_POS03_PAUSE_ACK_MISSING');
    const upload = parseReaderV5ProgressPut(latestRequest.postDataJSON());
    if (!upload) throw new Error('RG04_POS03_INVALID_REAL_PUT');
    expect(ackResponse.status()).toBe(200);
    expect(ackResponse.fromServiceWorker()).toBe(false);
    const ackPayload: unknown = await ackResponse.json();
    const ack = parseReaderV5ProgressWriteResult(responseData({ status: ackResponse.status(), payload: ackPayload }, progressPath));
    if (!ack) throw new Error('RG04_POS03_INVALID_REAL_ACK');
    expect(ack.acceptedMutationId).toBe(upload.mutationId);
    expect(ack.acceptedRevision).toBeGreaterThan(0);
    expect(ack.currentSnapshot).toMatchObject({ ...upload, revision: ack.acceptedRevision });
    await expect.poll(async () => {
      const stored = await storedProgress(page);
      return stored.pending.length === 0 && stored.exact.length === 1
        && optionalRecord(stored.exact[0])?.revision === ack.acceptedRevision;
    }).toBe(true);
    const confirmed = await storedProgress(page);
    const exact = record(confirmed.exact[0]);
    const identity = {
      serverIdentity: webOrigin, userId: stringValue(exact.userId, 'local userId'), clientId: upload.clientId,
      bookId: audio.bookId, resourceId: audio.resourceId
    };
    expect(confirmed).toEqual({ pending: [], exact: [{ ...identity, key: readerV5ProgressKey(identity), ...upload, revision: ack.acceptedRevision }] });
    const fresh = parseReaderV5ProgressSnapshot(
      responseData(await requestJson(page, webOrigin, progressPath, apiResponses), progressPath).progressSnapshot
    );
    expect(fresh).toEqual(ack.currentSnapshot);
    const confirmedMillis = numberValue(record(record(upload.position.presentation).playback).positionMillis, 'confirmed audio position');
    expect(Math.abs(confirmedMillis - paused.positionMillis)).toBeLessThanOrEqual(2_000);
    expect(Object.keys(record(upload.position.locator)).length).toBeGreaterThan(0);
    evidence.source = { bookId: audio.bookId, resourceId: audio.resourceId, startedPosition, pauseRequestedAt, paused, upload, ack, fresh, confirmed };
    await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/04-mp3-confirmed-before-kill.png') });
    screenshots.push('screenshots/04-mp3-confirmed-before-kill.png');

    evidence.phase = 'kill-confirmed-root';
    const verifiedRoot = await identifyDedicatedChrome(source.context, profile, source.startedAt);
    expect(verifiedRoot).toEqual(source.root);
    // Last guards run while the original page/context are still open. No
    // page close, context close, player close or navigation may flush progress.
    expect(page.isClosed()).toBe(false);
    expect(progressRequests.at(-1)).toBe(latestRequest);
    expect(await storedProgress(page)).toEqual(confirmed);
    expect(await engine.evaluate((element: HTMLAudioElement) => element.paused)).toBe(true);
    expect(apiResponses.filter((response) => response.status >= 500)).toEqual([]);
    evidence.kill = { root: verifiedRoot, signal: 'SIGKILL', beforeKillAt: Date.now(), pageOpen: true };
    await writeFile(resolve(manifest.artifactDir, 'process-recovery-before-kill.json'), `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
    // Recheck PID + creation time immediately before the destructive operation.
    expect(await readChromeProcess(verifiedRoot.pid)).toEqual(verifiedRoot);
    const browser = source.context.browser();
    if (!browser) throw new Error('dedicated source browser disappeared before kill');
    const killedAt = Date.now();
    process.kill(verifiedRoot.pid, 'SIGKILL');
    await expect.poll(() => browser.isConnected(), { timeout: 15_000 }).toBe(false);
    await expect.poll(() => readChromeProcess(verifiedRoot.pid), { timeout: 15_000 }).toBeNull();
    evidence.kill = { ...record(evidence.kill), killedAt, exitedAt: Date.now(), disconnected: true, rootAbsent: true };

    evidence.phase = 'restart-same-profile';
    const target = await launch(profile);
    expect(target.root.createdAt).not.toBe(source.root.createdAt);
    evidence.restartedRoot = target.root;
    const reopened = target.context.pages()[0] ?? await target.context.newPage();
    // The same-origin offline shell observes persisted stores before a reader
    // can capture a new position. It does not seed storage or replace login.
    await reopened.goto(`${webOrigin}/offline`, { waitUntil: 'domcontentloaded' });
    const afterRestart = await storedProgress(reopened);
    evidence.afterRestart = afterRestart;
    expect(afterRestart).toEqual(confirmed);
    expect(parseReaderV5ProgressSnapshot(
      responseData(await requestJson(reopened, webOrigin, progressPath, apiResponses), progressPath).progressSnapshot
    )).toEqual(ack.currentSnapshot);
    await reopened.goto(detailURL, { waitUntil: 'domcontentloaded' });
    await expect(reopened.getByText(audio.bookTitle, { exact: true }).first()).toBeVisible();
    const restoredPlayer = await openLiveAudioPlayer(reopened);
    await restoredPlayer.audioToggle.click();
    await expect(restoredPlayer.audioToggle).toHaveAttribute('aria-label', '播放');
    const restored = await reopened.locator('audio').evaluate((element: HTMLAudioElement) => ({
      paused: element.paused, positionMillis: element.currentTime * 1_000, durationMillis: element.duration * 1_000
    }));
    evidence.restored = { ...restored, confirmedMillis, errorMillis: Math.abs(restored.positionMillis - confirmedMillis) };
    expect(restored.paused).toBe(true);
    expect(restored.positionMillis).toBeGreaterThan(0);
    expect(Math.abs(restored.positionMillis - confirmedMillis)).toBeLessThanOrEqual(2_000);
    await reopened.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/05-mp3-restored-after-process-kill.png') });
    screenshots.push('screenshots/05-mp3-restored-after-process-kill.png');
    expect(apiResponses.filter((response) => response.status >= 500)).toEqual([]);
    evidence.phase = 'complete';
  } catch (error) {
    primaryFailure = safeFixtureError(error);
  } finally {
    // Close each owned context independently, including partial setup. Never
    // enumerate/kill arbitrary Chrome processes or touch a user profile.
    const closed = await Promise.allSettled(contexts.map((context) => context.close()));
    for (const [index, outcome] of closed.entries()) {
      cleanup.push({ context: index, outcome: outcome.status });
      if (outcome.status === 'rejected') cleanupFailure = combineFixtureErrors(cleanupFailure, safeFixtureError(outcome.reason));
    }
    for (const root of roots) {
      try {
        await expect.poll(() => readChromeProcess(root.pid), { timeout: 15_000 }).toBeNull();
        cleanup.push({ pid: root.pid, createdAt: root.createdAt, rootAbsent: true });
      } catch (error) { cleanupFailure = combineFixtureErrors(cleanupFailure, safeFixtureError(error)); }
    }
    if (profile && !cleanupFailure) {
      try {
        expect(dirname(profile)).toBe(resolve(REPO_ROOT, '.tmp'));
        expect(basename(profile)).toMatch(/^rg04-pos03-chrome-/);
        expect(await realpath(profile)).toBe(profile);
        await rm(profile, { recursive: true, maxRetries: 5, retryDelay: 200 });
        cleanup.push({ profile, removed: !existsSync(profile) });
        expect(existsSync(profile)).toBe(false);
      } catch (error) { cleanupFailure = combineFixtureErrors(cleanupFailure, safeFixtureError(error)); }
    }
    if (fixture) {
      try {
        const fixtureFailure = await stopFixture(fixture);
        if (fixtureFailure) throw new Error(fixtureFailure);
      } catch (error) { cleanupFailure = combineFixtureErrors(cleanupFailure, safeFixtureError(error)); }
      try {
        await writeFile(resolve(fixture.artifactDir, 'browser-observations.json'), `${JSON.stringify({
          result: primaryFailure || cleanupFailure ? 'FAILED' : 'PASS',
          failure: primaryFailure?.message ?? null, cleanupFailure: cleanupFailure?.message ?? null,
          repoHead: manifest?.repoHead ?? null, project: testInfo.project.name, noRouteMocks: true,
          importTaskFailures, responses: apiResponses, screenshots, cleanup, ...evidence
        }, null, 2)}\n`, 'utf8');
      } catch (error) { cleanupFailure = combineFixtureErrors(cleanupFailure, safeFixtureError(error)); }
    }
  }
  const error = combineFixtureErrors(primaryFailure, cleanupFailure);
  if (error) throw error;
});

test(`release live fresh install resumes EPUB and ${requestedAudioMime} through Reader v5`, async ({ page, context }, testInfo) => {
  test.setTimeout(FIXTURE_STARTUP_TIMEOUT_MS + 300_000 + audioSoakSeconds() * 1_000 + FIXTURE_STOP_TIMEOUT_MS);

  const password = livePassword();
  const apiResponses: ApiResponseObservation[] = [];
  const progressPaths = new Set<string>();
  const progressWrites: ProgressWriteObservation[] = [];
  const screenshots: string[] = [];
  let fixture: FixtureRun | null = null;
  let result = 'FAILED';
  let failure: string | null = null;
  let primaryFailure: Error | null = null;
  let cleanupFailure: Error | null = null;
  let manifest: LiveManifest | null = null;
  let audioObservation: JsonRecord | null = null;
  const importTaskFailures: JsonRecord[] = [];

  page.on('response', (response) => {
    const url = new URL(response.url());
    if (url.origin === (manifest?.webOrigin ?? '') && url.pathname.startsWith('/api/')) {
      apiResponses.push({ method: response.request().method(), path: `${url.pathname}${url.search}`, status: response.status() });
    }
  });
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'PUT' || !progressPaths.has(path)) return;
    const body = request.postData();
    if (!body) return;
    try {
      progressWrites.push({ path, body: JSON.parse(body) as unknown });
    } catch {
      progressWrites.push({ path, body: { parseError: true } });
    }
  });

  try {
    fixture = await startFixture(testInfo);
    manifest = fixture.manifest;
    if (!manifest) throw new Error('live fixture returned without a manifest');
    const { webOrigin } = manifest;
    const { catalog, epub } = await setupLiveCatalog(
      page, manifest, password, apiResponses, importTaskFailures, screenshots
    );
    const bookButton = page.getByRole('button', { name: new RegExp(escapeRegExp(epub.bookTitle)) }).first();
    await expect(bookButton).toBeVisible();
    await bookButton.click();
    await expect(page).toHaveURL(new RegExp(`/books/${escapeRegExp(epub.bookId)}(?:\\?|$)`));
    await expect(page.getByText(epub.bookTitle, { exact: true }).first()).toBeVisible();
    await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/04-epub-detail.png') });
    screenshots.push('screenshots/04-epub-detail.png');

    await openDetailResource(page, '打开阅读器');
    const frame = await visibleReaderFrame(page);
    await expect(frame.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
    await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/05-epub-reader-start.png') });
    screenshots.push('screenshots/05-epub-reader-start.png');

    const epubProgressPath = `/api/reader/v5/resources/${encodeURIComponent(epub.resourceId)}/progress`;
    progressPaths.add(epubProgressPath);
    await revealReaderControls(page);
    await page.getByRole('button', { name: '下一章', exact: true }).click();
    const chapterTwoFrame = await visibleReaderFrame(page);
    await expect(chapterTwoFrame.contentFrame().getByText('第二章 翻页验证')).toBeVisible();
    const epubProgressWrites = () => progressWrites.filter((write) => write.path === epubProgressPath);
    await expect.poll(() => epubProgressWrites().length, { timeout: 45_000 }).toBeGreaterThan(0);
    await expect.poll(
      () => epubProgressWrites().some((write) => JSON.stringify(write.body).includes('chapter2')),
      { timeout: 45_000 }
    ).toBe(true);
    await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/06-epub-reader-chapter2.png') });
    screenshots.push('screenshots/06-epub-reader-chapter2.png');

    const latestWrite = record(epubProgressWrites().at(-1)?.body);
    expect(latestWrite.schemaVersion).toBe(5);
    const writtenPosition = record(latestWrite.position);
    const writtenLocator = record(writtenPosition.locator);
    expect(Object.keys(writtenLocator).length).toBeGreaterThan(0);
    const writtenPresentation = record(writtenPosition.presentation);
    expect(writtenPresentation.displayPercent).toEqual(expect.any(Number));

    await revealReaderControls(page);
    await page.getByRole('button', { name: '返回详情页', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/books/${escapeRegExp(epub.bookId)}\\?resourceId=${escapeRegExp(epub.resourceId)}`));

    let bootstrapSnapshot: JsonRecord | null = null;
    const bootstrapPath = `/api/reader/v5/resources/${encodeURIComponent(epub.resourceId)}/bootstrap`;
    await expect.poll(async () => {
      const bootstrapResult = await requestJson(page, webOrigin, bootstrapPath, apiResponses);
      if (bootstrapResult.status < 200 || bootstrapResult.status >= 300) return false;
      const data = responseData(bootstrapResult, bootstrapPath);
      const snapshot = optionalRecord(data.progressSnapshot);
      const position = snapshot ? optionalRecord(snapshot.position) : null;
      const locator = position ? optionalRecord(position.locator) : null;
      if (!snapshot || !position || !locator || !JSON.stringify(locator).includes('chapter2')) return false;
      bootstrapSnapshot = snapshot;
      return true;
    }, { timeout: 45_000 }).toBe(true);
    const confirmedBootstrapSnapshot = record(bootstrapSnapshot);
    expect(confirmedBootstrapSnapshot.schemaVersion).toBe(5);

    await openDetailResource(page, '打开阅读器');
    const reopenedFrame = await visibleReaderFrame(page);
    await expect(reopenedFrame.contentFrame().getByText('第二章 翻页验证')).toBeVisible();
    await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/07-epub-reopened-chapter2.png') });
    screenshots.push('screenshots/07-epub-reopened-chapter2.png');

    const audio = catalog.find((entry) => (
      entry.readerType === 'audio'
      && entry.assetMimeTypes.includes(requestedAudioMime)
    ));
    expect(manifest.samples.some((sample) => sample.expectedMime === requestedAudioMime)).toBe(true);
    if (!audio) throw new Error(`real catalog did not contain the required ${requestedAudioMime} resource`);
    expect(audio.readerType).toBe('audio');
    await page.goto(
      `${webOrigin}/books/${encodeURIComponent(audio.bookId)}?resourceId=${encodeURIComponent(audio.resourceId)}`,
      { waitUntil: 'domcontentloaded' }
    );
    await expect(page.getByText(audio.bookTitle, { exact: true }).first()).toBeVisible();
    await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/08-audio-detail.png') });
    screenshots.push('screenshots/08-audio-detail.png');

    const audioProgressPath = `/api/reader/v5/resources/${encodeURIComponent(audio.resourceId)}/progress`;
    progressPaths.add(audioProgressPath);
    const { player, audioToggle } = await openLiveAudioPlayer(page);
    await audioToggle.click();
    await expect(audioToggle).toHaveAttribute('aria-label', '播放');
    await audioToggle.click();
    await expect(audioToggle).toHaveAttribute('aria-label', '暂停');

    // Observe real engine time against a fresh server read, without pause/seek
    // triggering lifecycle saves during the continuous-playback checkpoints.
    const continuousStartedAt = Date.now();
    let previousSavedPosition = 0;
    const continuousSaves: JsonRecord[] = [];
    for (const checkpoint of timingFixture.continuousCheckpointsMillis) {
      await delay(Math.max(0, continuousStartedAt + checkpoint - Date.now()));
      await expect(audioToggle).toHaveAttribute('aria-label', '暂停');
      const enginePosition = await page.locator('audio').evaluate(
        (element: HTMLAudioElement) => element.currentTime * 1_000
      );
      const readback = responseData(
        await requestJson(page, webOrigin, audioProgressPath, apiResponses),
        audioProgressPath
      );
      const savedSnapshot = record(readback.progressSnapshot);
      const savedPosition = record(savedSnapshot.position);
      const savedPlayback = record(record(savedPosition.presentation).playback);
      const savedMillis = numberValue(savedPlayback.positionMillis, 'continuous saved audio position');
      expect(savedMillis).toBeGreaterThan(previousSavedPosition);
      expect(enginePosition - savedMillis).toBeLessThanOrEqual(timingFixture.maxCaptureAgeMillis);
      continuousSaves.push({ checkpoint, enginePositionMillis: enginePosition, savedPositionMillis: savedMillis, revision: savedSnapshot.revision });
      previousSavedPosition = savedMillis;
    }

    if (audioSoakSeconds() > 0) {
      await observeAudioSoak(page, audioSoakSeconds(), resolve(manifest.artifactDir, 'audio-soak.jsonl'), async () => {
        const enginePosition = await page.locator('audio').evaluate((element: HTMLAudioElement) => element.currentTime * 1_000);
        const readback = responseData(await requestJson(page, webOrigin, audioProgressPath, apiResponses), audioProgressPath);
        const snapshot = record(readback.progressSnapshot);
        const savedMillis = numberValue(record(record(record(snapshot.position).presentation).playback).positionMillis, 'soak saved position');
        expect(savedMillis).toBeGreaterThan(previousSavedPosition);
        expect(enginePosition - savedMillis).toBeLessThanOrEqual(timingFixture.maxCaptureAgeMillis);
        continuousSaves.push({ checkpoint: Date.now() - continuousStartedAt, enginePositionMillis: enginePosition, savedPositionMillis: savedMillis, revision: snapshot.revision });
        previousSavedPosition = savedMillis;
      });
    }

    audioObservation = { resourceId: audio.resourceId, continuousSaves, soakSeconds: audioSoakSeconds() };
    const audioSlider = player.getByRole('slider', { name: '有声书播放进度' });
    await expect(audioSlider).toBeVisible();
    const audioMaximum = Number(await audioSlider.getAttribute('max'));
    expect(audioMaximum).toBeGreaterThan(0);
    const targetAudioPosition = Math.max(
      1_000,
      Math.min(audioMaximum - 1_000, Math.round(audioMaximum * 0.25 / 1_000) * 1_000)
    );
    const seekProbe = await startAudioProbe(page);
    const seekObservations: JsonRecord[] = [];
    try {
      seekObservations.push({ stage: 'before-seek', targetAudioPosition, ...await seekProbe.evaluate((value) => value.read()) });
      await audioSlider.fill(String(targetAudioPosition));
      await expect.poll(async () => Number(await audioSlider.inputValue()), { timeout: 10_000 })
        .toBe(targetAudioPosition);
      seekObservations.push({ stage: 'slider-target', ...await seekProbe.evaluate((value) => value.read()) });
      await audioToggle.click();
      await expect(audioToggle).toHaveAttribute('aria-label', '播放');
      seekObservations.push({ stage: 'paused', ...await seekProbe.evaluate((value) => value.read()) });
    } finally {
      await seekProbe.evaluate((value) => value.stop());
      await seekProbe.dispose();
      await writeFile(resolve(manifest.artifactDir, 'audio-seek-observations.json'), JSON.stringify(seekObservations, null, 2), 'utf8');
    }
    const audioProgressWrites = () => progressWrites.filter((write) => write.path === audioProgressPath);
    await expect.poll(() => audioProgressWrites().length, { timeout: 45_000 }).toBeGreaterThan(0);
    const latestAudioWrite = record(audioProgressWrites().at(-1)?.body);
    expect(latestAudioWrite.schemaVersion).toBe(5);
    const audioWrittenPosition = record(latestAudioWrite.position);
    const audioWrittenLocator = record(audioWrittenPosition.locator);
    expect(Object.keys(audioWrittenLocator).length).toBeGreaterThan(0);
    const audioWrittenPresentation = record(audioWrittenPosition.presentation);
    expect(audioWrittenPresentation.displayPercent).toEqual(expect.any(Number));
    const audioWrittenPlayback = record(audioWrittenPresentation.playback);
    expect(numberValue(audioWrittenPlayback.positionMillis, 'audio position')).toBeGreaterThan(0);
    await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/09-audio-playing-seeked.png') });
    screenshots.push('screenshots/09-audio-playing-seeked.png');

    const closeAudio = player.getByRole('button', { name: '关闭播放器', exact: true });
    await closeAudio.click();
    await expect(player).toHaveCount(0);
    await page.goto(
      `${webOrigin}/books/${encodeURIComponent(audio.bookId)}?resourceId=${encodeURIComponent(audio.resourceId)}`,
      { waitUntil: 'domcontentloaded' }
    );
    await openDetailResource(page, '打开播放器');
    const reopenedPlayer = page.getByTestId('audio-mini-player');
    await expect(reopenedPlayer).toBeVisible({ timeout: 30_000 });
    const reopenedAudioToggle = reopenedPlayer.getByTestId('audio-play-toggle');
    await expect(reopenedAudioToggle).toBeVisible({ timeout: 30_000 });
    await expect(reopenedAudioToggle).toHaveAttribute('aria-label', '暂停', { timeout: 30_000 });
    await reopenedAudioToggle.click();
    await expect(reopenedAudioToggle).toHaveAttribute('aria-label', '播放');
    const reopenedAudioSlider = reopenedPlayer.getByRole('slider', { name: '有声书播放进度' });
    await expect(reopenedAudioSlider).toBeVisible();
    const reopenedAudioPosition = Number(await reopenedAudioSlider.inputValue());
    expect(reopenedAudioPosition).toBeGreaterThan(0);
    expect(Math.abs(reopenedAudioPosition - targetAudioPosition)).toBeLessThanOrEqual(2_000);

    const audioBootstrapPath = `/api/reader/v5/resources/${encodeURIComponent(audio.resourceId)}/bootstrap`;
    const audioBootstrapResult = await requestJson(page, webOrigin, audioBootstrapPath, apiResponses);
    const audioBootstrapData = responseData(audioBootstrapResult, audioBootstrapPath);
    expect(audioBootstrapData.schemaVersion).toBe(5);
    expect(audioBootstrapData.readerType).toBe('audio');
    const audioSnapshot = record(audioBootstrapData.progressSnapshot);
    expect(audioSnapshot.schemaVersion).toBe(5);
    const audioSnapshotPosition = record(audioSnapshot.position);
    const audioSnapshotLocator = record(audioSnapshotPosition.locator);
    expect(Object.keys(audioSnapshotLocator).length).toBeGreaterThan(0);
    const audioSnapshotPresentation = record(audioSnapshotPosition.presentation);
    const audioSnapshotPlayback = record(audioSnapshotPresentation.playback);
    const storedAudioPosition = numberValue(audioSnapshotPlayback.positionMillis, 'stored audio position');
    expect(storedAudioPosition).toBeGreaterThan(0);
    audioObservation = {
      bookId: audio.bookId,
      resourceId: audio.resourceId,
      readerType: audio.readerType,
      progressPath: audioProgressPath,
      progressPutCount: audioProgressWrites().length,
      latestProgressBody: latestAudioWrite,
      bootstrapPath: audioBootstrapPath,
      bootstrapSchemaVersion: audioBootstrapData.schemaVersion,
      storedPositionMillis: storedAudioPosition,
      reopenedPositionMillis: reopenedAudioPosition,
      sourceFormat: audio.format,
      assetMimeTypes: audio.assetMimeTypes,
      continuousSaves
    };
    await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/10-audio-reopened-v5.png') });
    screenshots.push('screenshots/10-audio-reopened-v5.png');
    if (productionWeb) {
      const serviceWorker = await page.evaluate(async () => {
        const cacheEntries = await Promise.all((await caches.keys()).map(async (name) => ({
          name,
          paths: (await (await caches.open(name)).keys()).map((request) => new URL(request.url).pathname)
        })));
        return { controller: navigator.serviceWorker.controller?.scriptURL ?? null, cacheEntries };
      });
      await writeFile(resolve(manifest.artifactDir, 'service-worker-observations.json'), `${JSON.stringify(serviceWorker, null, 2)}\n`, 'utf8');
      expect(serviceWorker.controller).toBe(`${webOrigin}/sw.js`);
      const shell = serviceWorker.cacheEntries.find((cache) => cache.name.endsWith('-app-shell'));
      expect(shell?.paths).toContain('/offline');
      expect(shell?.paths).toContain('/login');
      // App-owned verified originals have a separate cache owner; only examine
      // the service worker's shell/static/API/cover caches for forbidden bodies.
      const workerPaths = serviceWorker.cacheEntries.filter((cache) => /-(app-shell|static|api|cover)$/.test(cache.name))
        .flatMap((cache) => cache.paths);
      expect(workerPaths.filter((path) => path.startsWith('/api/auth/') || path.startsWith('/api/reader/') || path.startsWith('/api/assets/'))).toEqual([]);
      await context.setOffline(true);
      try {
        await page.goto(`${webOrigin}/__release_offline_probe`, { waitUntil: 'domcontentloaded' });
        await expect(page.getByRole('heading', { name: '当前网络不可用', exact: true })).toBeVisible();
        await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/11-pwa-offline.png') });
        screenshots.push('screenshots/11-pwa-offline.png');
      } finally {
        await context.setOffline(false);
      }
      await page.goto(`${webOrigin}/`, { waitUntil: 'domcontentloaded' });
      const restoredAuth = await requestJson(page, webOrigin, '/api/auth/me', apiResponses);
      expect(restoredAuth.status).toBe(200);
      await writeFile(resolve(manifest.artifactDir, 'service-worker-observations.json'), `${JSON.stringify({
        ...serviceWorker, offlineNavigation: 'PASS', restoredAuthStatus: restoredAuth.status
      }, null, 2)}\n`, 'utf8');
    }
    expect(apiResponses.filter((response) => response.status >= 500)).toEqual([]);
    result = 'PASS';
  } catch (error) {
    primaryFailure = safeFixtureError(error);
    failure = primaryFailure.message;
  } finally {
    if (fixture) {
      try {
        const fixtureFailure = await stopFixture(fixture);
        if (fixtureFailure) throw new Error(fixtureFailure);
      } catch (error) {
        cleanupFailure = safeFixtureError(error);
        result = 'FAILED';
      }
      const observations = {
        result,
        failure,
        cleanupFailure: cleanupFailure?.message ?? null,
        audioEnvironment: {
          ffprobeAvailable: manifest?.ffprobeAvailable ?? false,
          ffprobePath: manifest?.ffprobePath ?? null,
          importTaskFailures,
          allCorpusAudioRequired: manifest?.ffprobeAvailable ?? false
        },
        scope: result === 'PASS'
          ? `fresh setup/admin, real login, FLAT library creation, real scan/worker import of EPUB/PDF/CBZ and MP3/AAC/WAV/FLAC, EPUB Reader v5 chapter progression and reopen, MIME-selected ${requestedAudioMime} UI play/pause/seek, continuous server persistence and v5 reopen`
          : 'live fixture started or partially completed; inspect failure and process logs before assigning product, fixture, or environment ownership',
        repoHead: manifest?.repoHead ?? null,
        apiOrigin: manifest?.apiOrigin ?? null,
        webOrigin: manifest?.webOrigin ?? null,
        libraryName: manifest?.libraryName ?? null,
        samples: manifest?.samples ?? [],
        responses: apiResponses,
        audio: audioObservation,
        progressPutCount: progressWrites.length,
        progressPutBodies: progressWrites,
        screenshots,
        processLogs: manifest?.processLogs ?? {},
        noRouteMocks: true,
        project: testInfo.project.name,
        webRuntime: productionWeb ? 'production' : 'development'
      };
      try {
        await writeFile(
          resolve(fixture.artifactDir, 'browser-observations.json'),
          `${JSON.stringify(observations, null, 2)}\n`,
          'utf8'
        );
      } catch (error) {
        cleanupFailure = combineFixtureErrors(cleanupFailure, safeFixtureError(error));
      }
    }
  }
  const error = combineFixtureErrors(primaryFailure, cleanupFailure);
  if (error) throw error;
});

test('release live EPUB preserves offline pending across page rebuild and confirms on reconnect', async ({ page, context }, testInfo) => {
  test.setTimeout(FIXTURE_STARTUP_TIMEOUT_MS + 300_000 + FIXTURE_STOP_TIMEOUT_MS);
  // RG04/POS04 (DEC07): the existing online reopen case cannot prove durable
  // offline pending. The production offline page is only a same-origin observer,
  // not an offline login/reader contract or a browser-process termination probe.
  if (!productionWeb) throw new Error('RG04_POS04 requires RELEASE_LIVE_WEB_RUNTIME=production and the real service worker');
  const password = livePassword();
  const apiResponses: ApiResponseObservation[] = [];
  const importTaskFailures: JsonRecord[] = [];
  const screenshots: string[] = [];
  const evidence: JsonRecord = { gate: 'RG04/POS04', phase: 'setup' };
  let fixture: FixtureRun | null = null;
  let manifest: LiveManifest | null = null;
  let rebuilt: Page | null = null;
  let primaryFailure: Error | null = null;
  let cleanupFailure: Error | null = null;
  let progressPath: string | null = null;
  let expectedMutationId: string | null = null;
  let reconnecting = false;
  const confirmation: { sendableAt: number | null; responseAt: number | null; response: Response | null } = {
    sendableAt: null, responseAt: null, response: null
  };

  context.on('response', (response) => {
    const url = new URL(response.url());
    if (url.origin !== manifest?.webOrigin || !url.pathname.startsWith('/api/')) return;
    const method = response.request().method();
    apiResponses.push({ method, path: `${url.pathname}${url.search}`, status: response.status() });
    if (!reconnecting) return;
    // The rebuilt offline page has no authenticated runtime. Start before the
    // successful /me response is consumed and activateReaderUser loads pending;
    // do not hide activation/queue time by starting the budget at the PUT.
    if (method === 'GET' && url.pathname === '/api/auth/me' && response.status() === 200) {
      confirmation.sendableAt ??= Date.now();
    }
    if (method === 'PUT' && url.pathname === progressPath && expectedMutationId
      && response.request().postData()?.includes(JSON.stringify(expectedMutationId))) {
      confirmation.response ??= response;
      confirmation.responseAt ??= Date.now();
    }
  });

  try {
    fixture = await startFixture(testInfo);
    manifest = fixture.manifest;
    if (!manifest) throw new Error('live fixture returned without a manifest');
    const { webOrigin } = manifest;
    const { epub } = await setupLiveCatalog(page, manifest, password, apiResponses, importTaskFailures, screenshots);
    const readerURL = `${webOrigin}/reader/${encodeURIComponent(epub.resourceId)}`;
    progressPath = `/api/reader/v5/resources/${encodeURIComponent(epub.resourceId)}/progress`;
    expect(responseData(await requestJson(page, webOrigin, progressPath, apiResponses), progressPath).progressSnapshot).toBeNull();
    await page.goto(`${webOrigin}/books/${encodeURIComponent(epub.bookId)}?resourceId=${encodeURIComponent(epub.resourceId)}`, { waitUntil: 'domcontentloaded' });
    await openDetailResource(page, '打开阅读器');
    const firstFrame = await visibleReaderFrame(page);
    await expect(firstFrame.contentFrame().getByRole('heading', { name: '第一章 开始阅读', exact: true })).toBeVisible();
    await expect.poll(async () => {
      const stored = await storedProgress(page);
      const exact = optionalRecord(stored.exact[0]);
      return stored.pending.length === 0 && stored.exact.length === 1
        && typeof exact?.revision === 'number' && exact.revision > 0;
    }).toBe(true);
    const initial = await storedProgress(page);
    const initialExact = record(initial.exact[0]);
    const identity = {
      serverIdentity: webOrigin,
      userId: stringValue(initialExact.userId, 'local userId'),
      clientId: stringValue(initialExact.clientId, 'local clientId'),
      bookId: epub.bookId,
      resourceId: epub.resourceId
    };
    expect(initialExact).toMatchObject({ ...identity, key: readerV5ProgressKey(identity), schemaVersion: 5 });
    const initialServer = parseReaderV5ProgressSnapshot(
      responseData(await requestJson(page, webOrigin, progressPath, apiResponses), progressPath).progressSnapshot
    );
    expect(initialServer).toMatchObject({
      schemaVersion: 5, clientId: identity.clientId, mutationId: initialExact.mutationId,
      revision: initialExact.revision, capturedAtEpochMillis: initialExact.capturedAtEpochMillis,
      position: initialExact.position
    });
    evidence.initial = initial;

    evidence.phase = 'offline-capture';
    await context.setOffline(true);
    expect(await page.evaluate(() => navigator.onLine)).toBe(false);
    const offlineAt = Date.now();
    await revealReaderControls(page);
    await page.getByRole('button', { name: '下一章', exact: true }).click();
    const offlineFrame = await visibleReaderFrame(page);
    await expect(offlineFrame.contentFrame().getByRole('heading', { name: '第二章 翻页验证', exact: true })).toBeVisible();
    await expect.poll(async () => {
      const stored = await storedProgress(page);
      const pending = optionalRecord(stored.pending[0]);
      const locator = optionalRecord(optionalRecord(pending?.position)?.locator);
      return stored.pending.length === 1 && typeof locator?.href === 'string'
        && /(?:^|\/)chapter2\.xhtml(?:#|$)/.test(locator.href);
    }).toBe(true);
    const offline = await storedProgress(page);
    evidence.offline = offline;
    const pending = record(offline.pending[0]);
    const upload = parseReaderV5ProgressPut({
      schemaVersion: pending.schemaVersion, clientId: pending.clientId, mutationId: pending.mutationId,
      capturedAtEpochMillis: pending.capturedAtEpochMillis, position: pending.position
    });
    if (!upload) throw new Error('RG04_POS04_INVALID_REAL_PENDING');
    expect(pending).toEqual({ ...identity, key: initialExact.key, ...upload });
    expect(offline.exact).toEqual([{ ...pending, revision: initialExact.revision }]);
    expect(upload.mutationId).not.toBe(initialExact.mutationId);
    expect(upload.capturedAtEpochMillis).toBeGreaterThan(numberValue(initialExact.capturedAtEpochMillis, 'initial capturedAt'));
    expect(upload.capturedAtEpochMillis).toBeGreaterThanOrEqual(offlineAt);
    expect(upload.position).not.toEqual(initialExact.position);
    const locator = record(upload.position.locator);
    expect(locator.href).toMatch(/(?:^|\/)chapter2\.xhtml(?:#|$)/);
    expect(locator.type).toBe('application/xhtml+xml');
    expect(Object.keys(record(locator.locations)).length).toBeGreaterThan(0);
    await page.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/04-epub-offline-pending.png') });
    screenshots.push('screenshots/04-epub-offline-pending.png');

    evidence.phase = 'offline-page-rebuild';
    await page.close();
    rebuilt = await context.newPage();
    const offlineResponse = await rebuilt.goto(`${webOrigin}/offline`, { waitUntil: 'domcontentloaded' });
    expect(offlineResponse?.fromServiceWorker()).toBe(true);
    await expect(rebuilt.getByRole('heading', { name: '当前网络不可用', exact: true })).toBeVisible();
    expect(await rebuilt.evaluate(() => ({ origin: location.origin, online: navigator.onLine })))
      .toEqual({ origin: webOrigin, online: false });
    const afterRebuild = await storedProgress(rebuilt);
    evidence.afterRebuild = afterRebuild;
    expect(afterRebuild).toEqual(offline);

    evidence.phase = 'reconnect-confirmation';
    expectedMutationId = upload.mutationId;
    reconnecting = true;
    await context.setOffline(false);
    await rebuilt.goto(readerURL, { waitUntil: 'domcontentloaded' });
    await expect.poll(() => confirmation.sendableAt, { message: 'rebuilt page must obtain its real authenticated session' }).not.toBeNull();
    const sendableAt = numberValue(confirmation.sendableAt, 'pending sendableAt');
    // release-gate RG04: five seconds from sendable pending, including ACK
    // application to IndexedDB and the independent, uncached server readback.
    const deadline = sendableAt + 5_000;
    const remaining = () => {
      const millis = deadline - Date.now();
      if (millis <= 0) throw new Error('RG04_POS04_CONFIRMATION_DEADLINE');
      return millis;
    };
    await expect.poll(() => confirmation.response !== null, { timeout: remaining() }).toBe(true);
    const ackResponse = confirmation.response;
    if (!ackResponse) throw new Error('RG04_POS04_PENDING_ACK_MISSING');
    expect(numberValue(confirmation.responseAt, 'ACK responseAt')).toBeGreaterThanOrEqual(sendableAt);
    expect(ackResponse.fromServiceWorker()).toBe(false);
    expect(parseReaderV5ProgressPut(ackResponse.request().postDataJSON())).toEqual(upload);
    const ackPayload: unknown = await ackResponse.json();
    const ack = parseReaderV5ProgressWriteResult(responseData({ status: ackResponse.status(), payload: ackPayload }, progressPath));
    if (!ack) throw new Error('RG04_POS04_INVALID_REAL_ACK');
    evidence.ack = ack;
    expect(ack.acceptedMutationId).toBe(upload.mutationId);
    expect(ack.acceptedRevision).toBeGreaterThan(numberValue(initialExact.revision, 'initial revision'));
    expect(ack.currentSnapshot).toMatchObject({ ...upload, revision: ack.acceptedRevision });
    const confirmedLocal = { pending: [], exact: [{ ...pending, revision: ack.acceptedRevision }] };
    const confirmationPage = rebuilt;
    await expect.poll(() => storedProgress(confirmationPage), { timeout: remaining() }).toEqual(confirmedLocal);
    const fresh = parseReaderV5ProgressSnapshot(
      responseData(await requestJson(rebuilt, webOrigin, progressPath, apiResponses), progressPath).progressSnapshot
    );
    evidence.freshServer = fresh;
    expect(fresh).toEqual(ack.currentSnapshot);
    const confirmed = await storedProgress(rebuilt);
    evidence.confirmed = confirmed;
    expect(confirmed).toEqual(confirmedLocal);
    const confirmedAt = Date.now();
    evidence.confirmation = { sendableAt, responseAt: confirmation.responseAt, confirmedAt, elapsedMillis: confirmedAt - sendableAt };
    expect(confirmedAt - sendableAt).toBeLessThanOrEqual(5_000);

    const restoredFrame = await visibleReaderFrame(rebuilt);
    await expect(restoredFrame.contentFrame().getByRole('heading', { name: '第二章 翻页验证', exact: true })).toBeVisible();
    await rebuilt.screenshot({ path: resolve(manifest.artifactDir, 'screenshots/05-epub-reconnected-chapter2.png') });
    screenshots.push('screenshots/05-epub-reconnected-chapter2.png');
    expect(apiResponses.filter((response) => response.status >= 500)).toEqual([]);
    evidence.phase = 'complete';
  } catch (error) {
    primaryFailure = safeFixtureError(error);
  } finally {
    try {
      for (const ownedPage of [page, rebuilt]) {
        if (ownedPage && !ownedPage.isClosed()) await ownedPage.close();
      }
      await context.setOffline(false);
    } catch (error) {
      cleanupFailure = safeFixtureError(error);
    }
    if (fixture) {
      try {
        const fixtureFailure = await stopFixture(fixture);
        if (fixtureFailure) throw new Error(fixtureFailure);
      } catch (error) {
        cleanupFailure = combineFixtureErrors(cleanupFailure, safeFixtureError(error));
      }
      try {
        await writeFile(resolve(fixture.artifactDir, 'browser-observations.json'), `${JSON.stringify({
          result: primaryFailure || cleanupFailure ? 'FAILED' : 'PASS',
          failure: primaryFailure?.message ?? null, cleanupFailure: cleanupFailure?.message ?? null,
          repoHead: manifest?.repoHead ?? null, project: testInfo.project.name,
          noRouteMocks: true, importTaskFailures, responses: apiResponses, screenshots, ...evidence
        }, null, 2)}\n`, 'utf8');
      } catch (error) {
        cleanupFailure = combineFixtureErrors(cleanupFailure, safeFixtureError(error));
      }
    }
  }
  const error = combineFixtureErrors(primaryFailure, cleanupFailure);
  if (error) throw error;
});
