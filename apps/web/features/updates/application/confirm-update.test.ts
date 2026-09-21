import assert from 'node:assert/strict';
import test from 'node:test';
import { confirmUpdate } from './confirm-update';
import { canInstall, confirmedSuccess, installationFailed, runningWithoutRecord } from '../model/installation';
import { installUpdate, parsePreparation, prepareUpdate } from '../api/operations';
import type { Package, PreparationState } from '@/generated/updates';

const target: Package = { version: '1.0.5', format: 1, sha256: 'a'.repeat(64), filename: 'shuku-1.0.5-linux-x86_64.tar.gz', size: 10, expanded_size: 20, file_count: 2, environment: { format: 1, platform: 'linux-x86_64', compatibility: 'b'.repeat(64) } };
const ready: PreparationState = { phase: 'ready', target, downloaded: 10, error: null };
test('first confirmation only prepares; ready is not successful installation', async () => {
  const calls: string[] = [];
  await confirmUpdate('prepare', target, async () => true, async operation => { calls.push(operation); });
  assert.deepEqual(calls, ['prepare']);
  assert.equal(confirmedSuccess(ready, target.version), false);
});
test('cancelling installation submits nothing; confirmed identity cannot drift', async () => {
  const calls: unknown[] = [];
  const displayed = { ...target };
  await confirmUpdate('install', displayed, async () => false, async (...args) => { calls.push(args); });
  assert.equal(calls.length, 0);
  await confirmUpdate('install', displayed, async () => { displayed.sha256 = 'c'.repeat(64); return true; }, async (...args) => { calls.push(args); });
  assert.deepEqual(calls, [['install', { version: target.version, sha256: target.sha256 }]]);
});
test('success requires actual running version and persisted package identity', () => {
  const success = { ...ready, phase: 'success' as const };
  assert.equal(confirmedSuccess(success, '1.0.4', target), false);
  assert.equal(confirmedSuccess(success, target.version, { ...target, sha256: 'c'.repeat(64) }), false);
  assert.equal(confirmedSuccess(success, target.version, target), true);
  assert.equal(installationFailed({ phase: 'failed', failed_phase: 'verifying' }), false);
  assert.equal(installationFailed({ phase: 'failed', failed_phase: 'starting' }), true);
  assert.throws(() => parsePreparation({ phase: 'unknown' }));
});
test('HTTP adapter sends only selected operation and exact package identity', async t => {
  const calls: { path: string; body: unknown }[] = [];
  t.mock.method(globalThis, 'fetch', async (path: string, init: RequestInit) => {
    calls.push({ path, body: JSON.parse(String(init.body)) });
    return new Response(JSON.stringify({ ok: true, data: ready }), { status: 202 });
  });
  assert.equal((await prepareUpdate(target.version)).phase, 'ready');
  assert.deepEqual(calls, [{ path: '/api/updates/prepare', body: { version: target.version } }]);
  await installUpdate({ version: target.version, sha256: target.sha256 });
  assert.deepEqual(calls[1], { path: '/api/updates/install', body: { version: target.version, sha256: target.sha256 } });
});

test('protocol 2 state carries a manifest reference and bounded preparation summary', () => {
  const reference = { format: 2, version: target.version, environment: target.environment, filename: 'shuku-1.0.5-linux-x86_64-v2.json', size: 1000, sha256: target.sha256 };
  const summary = { dependency_identity: 'b'.repeat(64), baseline: 'c'.repeat(64), code_sha256: 'd'.repeat(64), keep: 58, install: 1, remove: 0, total_bytes: 12000, dependency_bytes: 10240, verified_artifacts: 2 };
  const state = parsePreparation({ phase: 'ready', target: reference, summary, downloaded: 12000 });
  assert.deepEqual(state.target, reference);
  assert.deepEqual(state.summary, summary);
  assert.equal(confirmedSuccess(state, target.version), false);
  assert.throws(() => parsePreparation({ ...state, summary: { ...summary, total_bytes: -1 } }));
});


test('protocol 2 accepts legacy plan metadata but binds success to confirmed package', async () => {
  const reference = { format: 2 as const, version: target.version, environment: target.environment, filename: 'shuku-1.0.5-linux-x86_64-v2.json', size: 1000, sha256: target.sha256 };
  const summary = { plan_sha256: 'e'.repeat(64), dependency_identity: 'b'.repeat(64), baseline: 'c'.repeat(64), code_sha256: 'd'.repeat(64), keep: 58, install: 1, remove: 0, total_bytes: 12000, dependency_bytes: 10240, verified_artifacts: 2 };
  const state = parsePreparation({ phase: 'success', target: reference, summary, downloaded: 12000 });
  assert.deepEqual(state.summary, summary);
  const displayed = { version: target.version, sha256: target.sha256, plan_sha256: summary.plan_sha256 };
  const expected = { ...displayed };
  await confirmUpdate('install', displayed, async () => { displayed.plan_sha256 = 'f'.repeat(64); return true; }, async (_, captured) => { assert.deepEqual(captured, expected); });
  assert.equal(confirmedSuccess(state, target.version, expected), true);
  assert.equal(confirmedSuccess(state, target.version, displayed), true);
  assert.equal(confirmedSuccess(state, '1.0.4', expected), false);
  assert.equal(confirmedSuccess({ ...state, target: { ...reference, sha256: 'f'.repeat(64) } }, target.version, expected), false);
  assert.equal(parsePreparation({ ...state, summary: { ...summary, plan_sha256: 'legacy-value' } }).summary?.plan_sha256, 'legacy-value');
});

test('POST carries the full protocol 2 plan exactly once', async t => {
  const identity = { version: target.version, sha256: target.sha256, plan_sha256: 'e'.repeat(64) };
  const calls: unknown[] = [];
  t.mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify({ ok: true, data: { phase: 'requested', target, downloaded: 10 } }));
  });
  await installUpdate(identity);
  assert.deepEqual(calls, [identity]);
});


test('protocol 2 can install a ready package without a plan digest', () => {
  const state = { phase: 'ready' as const, target: { ...target, format: 2 as const } };
  assert.equal(canInstall(state, 2), true);
  const ready = parsePreparation({ ...state, downloaded: 10, summary: { plan_sha256: 'e'.repeat(64), dependency_identity: 'b'.repeat(64), baseline: 'c'.repeat(64), code_sha256: 'd'.repeat(64), keep: 2, install: 0, remove: 0, total_bytes: 10, dependency_bytes: 0, verified_artifacts: 1 } });
  assert.equal(canInstall(ready, 0), false);
  assert.equal(canInstall(ready, 1), false);
  assert.equal(canInstall(ready, 2), true);
  assert.equal(canInstall({ ...ready, phase: 'success' }, 2), false);
});

test('applied confirms only the target actually running, with request binding', () => {
  const applied = parsePreparation({ ...ready, phase: 'applied' });
  assert.equal(confirmedSuccess(applied, '1.0.4', target), false);
  assert.equal(confirmedSuccess(applied, target.version, target), true);
  assert.equal(confirmedSuccess(applied, target.version, { ...target, sha256: 'f'.repeat(64) }), false);
  assert.equal(runningWithoutRecord(target.version, target), true);
  assert.equal(runningWithoutRecord('1.0.4', target), false);
  assert.equal(runningWithoutRecord(target.version, null), false);
});
