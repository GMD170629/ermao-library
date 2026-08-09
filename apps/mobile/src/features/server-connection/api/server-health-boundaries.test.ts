import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  ApiRequest,
  ApiTransport,
  ApiTransportResult,
} from '../../../shared/api/public';
import { AbortSignalCancellationToken } from '../infrastructure/abort-signal-cancellation-token';
import { parseServerAddress } from '../model/server-address';
import { ServerHealthClient } from './server-health-client';

function serverBaseUrl() {
  const parsed = parseServerAddress('http://192.168.1.20:3000');
  assert.equal(parsed.ok, true);
  if (!parsed.ok) {
    assert.fail('Expected a valid LAN library web address');
  }
  return parsed.baseUrl;
}

class CapturingTransport implements ApiTransport {
  capturedRequest: ApiRequest | null = null;

  constructor(private readonly result: ApiTransportResult) {}

  async request(request: ApiRequest): Promise<ApiTransportResult> {
    this.capturedRequest = request;
    return this.result;
  }
}

test('rejects an oversized health response as incompatible', async () => {
  const transport = new CapturingTransport({
    ok: false,
    reason: 'response-too-large',
    status: 200,
  });

  const result = await new ServerHealthClient(transport).probe(
    serverBaseUrl(),
  );

  assert.deepEqual(result, {
    outcome: 'incompatible',
    reason: 'invalid-response',
    status: 200,
  });
  assert.equal(transport.capturedRequest?.maximumResponseBytes, 16 * 1024);
});

test('maps platform abort signals to capability-level cancellation', async () => {
  const controller = new AbortController();
  controller.abort();
  const transport: ApiTransport = {
    async request(request) {
      assert.equal(request.signal?.aborted, true);
      return { ok: false, reason: 'aborted' };
    },
  };

  const result = await new ServerHealthClient(transport).probe(
    serverBaseUrl(),
    new AbortSignalCancellationToken(controller.signal),
  );

  assert.deepEqual(result, {
    outcome: 'unreachable',
    reason: 'cancelled',
  });
});
