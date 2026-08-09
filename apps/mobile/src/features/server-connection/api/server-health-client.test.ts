import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  ApiRequest,
  ApiTransport,
  ApiTransportResult,
} from '../../../shared/api/public';
import { parseServerAddress } from '../model/server-address';
import { ServerHealthClient } from './server-health-client';

const responseHeaders = {
  contentType: 'application/json',
  etag: null,
  lastModified: null,
} as const;

class StubTransport implements ApiTransport {
  readonly requests: ApiRequest[] = [];
  private nextResult = 0;

  constructor(private readonly results: readonly ApiTransportResult[]) {}

  async request(request: ApiRequest): Promise<ApiTransportResult> {
    this.requests.push(request);
    const result = this.results[this.nextResult];
    this.nextResult += 1;
    if (result === undefined) {
      throw new Error('Stub transport has no result for this request');
    }
    return result;
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
  const transport = new StubTransport([
    {
      ok: true,
      responseType: 'json',
      status: 200,
      headers: responseHeaders,
      body: {
        ok: true,
        data: { service: 'ermao-books', status: 'ok' },
      },
    },
    {
      ok: true,
      responseType: 'json',
      status: 200,
      headers: responseHeaders,
      body: { ok: true, data: { initialized: true } },
    },
  ]);
  const result = await new ServerHealthClient(transport).probe(
    serverBaseUrl(),
  );
  assert.deepEqual(result, { outcome: 'healthy', initialized: true });
  assert.deepEqual(
    transport.requests.map((request) => request.url),
    [
      'http://192.168.1.20:3000/api/health',
      'http://192.168.1.20:3000/api/auth/setup/status',
    ],
  );
});

test('keeps an identified 503 server distinct from an invalid server', async () => {
  const unhealthy = new ServerHealthClient(
    new StubTransport([{
      ok: true,
      responseType: 'json',
      status: 503,
      headers: responseHeaders,
      body: {
        ok: true,
        data: { service: 'ermao-books', status: 'error' },
      },
    }]),
  );
  assert.deepEqual(await unhealthy.probe(serverBaseUrl()), {
    outcome: 'unhealthy',
    status: 'error',
  });

  const incompatible = new ServerHealthClient(
    new StubTransport([{
      ok: true,
      responseType: 'json',
      status: 200,
      headers: responseHeaders,
      body: { ok: true, data: { service: 'another-app', status: 'ok' } },
    }]),
  );
  assert.deepEqual(await incompatible.probe(serverBaseUrl()), {
    outcome: 'incompatible',
    reason: 'invalid-response',
    status: 200,
  });
});

test('preserves transport failure categories', async () => {
  const client = new ServerHealthClient(
    new StubTransport([{ ok: false, reason: 'timeout' }]),
  );
  assert.deepEqual(await client.probe(serverBaseUrl()), {
    outcome: 'unreachable',
    reason: 'timeout',
  });
});

test('maps invalid JSON with an HTTP status to incompatible', async () => {
  const client = new ServerHealthClient(
    new StubTransport([{
      ok: false,
      reason: 'invalid-json',
      status: 404,
    }]),
  );
  assert.deepEqual(await client.probe(serverBaseUrl()), {
    outcome: 'incompatible',
    reason: 'invalid-response',
    status: 404,
  });
});
