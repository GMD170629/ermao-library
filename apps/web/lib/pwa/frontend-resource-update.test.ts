import assert from 'node:assert/strict';
import test from 'node:test';
import { checkFrontendResourceVersion, decodeFrontendResourceStatus } from './frontend-resource-update';

test('frontend resource status validates the typed backend envelope', () => {
  assert.deepEqual(decodeFrontendResourceStatus({
    ok: true,
    data: { frontendResources: { latestVersion: '1.2.3', updateRequired: true } }
  }), { latestVersion: '1.2.3', updateRequired: true });
});

test('frontend resource status rejects malformed or prerelease versions', () => {
  assert.throws(() => decodeFrontendResourceStatus({ ok: true, data: {} }), /响应无效/u);
  assert.throws(() => decodeFrontendResourceStatus({
    ok: true,
    data: { frontendResources: { latestVersion: '1.2.3-beta.1', updateRequired: false } }
  }), /响应无效/u);
});

test('a legacy worker that cannot report its version is declared stale to the backend', async () => {
  let reportedVersion = '';
  const worker = { postMessage() {} } as unknown as ServiceWorker;
  const result = await checkFrontendResourceVersion(
    worker,
    '/api/app-config',
    async (_input, init) => {
      reportedVersion = new Headers(init?.headers).get('X-Shuku-Frontend-Resource-Version') ?? '';
      return new Response(JSON.stringify({
        ok: true,
        data: { frontendResources: { latestVersion: '1.2.3', updateRequired: true } }
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    },
    5
  );
  assert.equal(reportedVersion, 'legacy-cache');
  assert.equal(result.status.updateRequired, true);
});
