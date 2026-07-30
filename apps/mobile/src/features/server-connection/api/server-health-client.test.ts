import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  JsonGetRequest,
  JsonTransport,
  JsonTransportResult,
} from '../../../shared/api/json-transport';
import { parseServerAddress } from '../model/server-address';
import { ServerHealthClient } from './server-health-client';

class StubTransport implements JsonTransport {
  request: JsonGetRequest | null = null;

  constructor(private readonly result: JsonTransportResult) {}

  async get(request: JsonGetRequest): Promise<JsonTransportResult> {
    this.request = request;
    return this.result;
  }
}

function serverBaseUrl() {
  const parsed = parseServerAddress('http://192.168.1.20:3000');
  assert.equal(parsed.ok, true);
  if (!parsed.ok) {
    throw new Error('Test address must be valid');
  }
  return parsed.baseUrl;
}

test('recognizes a healthy Shuku server', async () => {
  const transport = new StubTransport({
    ok: true,
    status: 200,
    body: {
      ok: true,
      data: { service: 'ermao-books', status: 'ok' },
    },
  });
  const result = await new ServerHealthClient(transport).probe(
    serverBaseUrl(),
  );
  assert.deepEqual(result, { outcome: 'healthy' });
  assert.equal(
    transport.request?.url,
    'http://192.168.1.20:3000/api/health',
  );
});

test('keeps an identified 503 server distinct from an invalid server', async () => {
  const unhealthy = new ServerHealthClient(
    new StubTransport({
      ok: true,
      status: 503,
      body: {
        ok: true,
        data: { service: 'ermao-books', status: 'error' },
      },
    }),
  );
  assert.deepEqual(await unhealthy.probe(serverBaseUrl()), {
    outcome: 'unhealthy',
    status: 'error',
  });

  const incompatible = new ServerHealthClient(
    new StubTransport({
      ok: true,
      status: 200,
      body: { ok: true, data: { service: 'another-app', status: 'ok' } },
    }),
  );
  assert.deepEqual(await incompatible.probe(serverBaseUrl()), {
    outcome: 'incompatible',
    reason: 'invalid-response',
    status: 200,
  });
});

test('preserves transport failure categories', async () => {
  const client = new ServerHealthClient(
    new StubTransport({ ok: false, reason: 'timeout' }),
  );
  assert.deepEqual(await client.probe(serverBaseUrl()), {
    outcome: 'unreachable',
    reason: 'timeout',
  });
});

test('maps invalid JSON with an HTTP status to incompatible', async () => {
  const client = new ServerHealthClient(
    new StubTransport({
      ok: false,
      reason: 'invalid-json',
      status: 404,
    }),
  );
  assert.deepEqual(await client.probe(serverBaseUrl()), {
    outcome: 'incompatible',
    reason: 'invalid-response',
    status: 404,
  });
});
