import assert from 'node:assert/strict';
import test from 'node:test';
import {
  probeApplicationReachability,
  resolveApplicationOnline
} from './network-availability';

test('application reachability overrides a false browser online hint', async () => {
  const online = await resolveApplicationOnline(false, async () => true);

  assert.equal(online, true);
});

test('an online browser hint does not perform an unnecessary reachability probe', async () => {
  let probeCalls = 0;

  const online = await resolveApplicationOnline(true, async () => {
    probeCalls += 1;
    return false;
  });

  assert.equal(online, true);
  assert.equal(probeCalls, 0);
});

test('an unreachable application confirms an offline browser hint', async () => {
  const online = await resolveApplicationOnline(false, async () => false);

  assert.equal(online, false);
});

test('any HTTP response proves that the application origin is reachable', async () => {
  const online = await probeApplicationReachability(
    '/api/app-config',
    async () => new Response(null, { status: 503 })
  );

  assert.equal(online, true);
});

test('a rejected reachability request is treated as offline', async () => {
  const online = await probeApplicationReachability(
    '/api/app-config',
    async () => {
      throw new TypeError('network unavailable');
    }
  );

  assert.equal(online, false);
});

test('a reachability request that does not settle times out as offline', async () => {
  const online = await probeApplicationReachability(
    '/api/app-config',
    async () => new Promise<Response>(() => undefined),
    1
  );

  assert.equal(online, false);
});
