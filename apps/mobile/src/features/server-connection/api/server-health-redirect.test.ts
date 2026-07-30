import assert from 'node:assert/strict';
import test from 'node:test';

import {
  FetchJsonTransport,
  type FetchFunction,
} from '../../../shared/api/json-transport';
import { parseServerAddress } from '../model/server-address';
import { ServerHealthClient } from './server-health-client';

test('does not follow redirects while identifying a server', async () => {
  let redirectPolicy: 'manual' | null = null;
  const fetchFunction: FetchFunction = async (_url, request) => {
    redirectPolicy = request.redirect;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            JSON.stringify({
              ok: true,
              data: { service: 'ermao-books', status: 'ok' },
            }),
          ),
        );
        controller.close();
      },
    });
    return { body, status: 302 };
  };
  const parsed = parseServerAddress('http://192.168.1.20:3000');
  assert.equal(parsed.ok, true);
  if (!parsed.ok) {
    assert.fail('Expected a valid LAN server address');
  }

  const result = await new ServerHealthClient(
    new FetchJsonTransport(fetchFunction),
  ).probe(parsed.baseUrl);

  assert.equal(redirectPolicy, 'manual');
  assert.deepEqual(result, {
    outcome: 'incompatible',
    reason: 'unexpected-http-status',
    status: 302,
  });
});
