import assert from 'node:assert/strict';
import http from 'node:http';
import test from 'node:test';
import { createUnifiedGateway } from './unified-http-gateway.mjs';

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address === 'object');
  return address.port;
}

async function close(server) {
  await new Promise((resolve, reject) => {
    server.close((error) => error ? reject(error) : resolve());
  });
}

test('streams API request bodies larger than the Next.js proxy limit without truncation', async (context) => {
  const expected = Buffer.alloc(12 * 1024 * 1024, 0x5a);
  const api = http.createServer((request, response) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      const received = Buffer.concat(chunks);
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({
        bytes: received.length,
        intact: received.equals(expected),
        path: request.url
      }));
    });
  });
  const web = http.createServer((_request, response) => response.end('web'));
  const apiPort = await listen(api);
  const webPort = await listen(web);
  const gateway = createUnifiedGateway({ apiPort, webPort });
  const gatewayPort = await listen(gateway);
  context.after(async () => Promise.all([close(gateway), close(api), close(web)]));

  const response = await fetch(`http://127.0.0.1:${gatewayPort}/api/works/import?source=test`, {
    method: 'POST',
    headers: { 'content-type': 'application/octet-stream' },
    body: expected
  });

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    bytes: expected.length,
    intact: true,
    path: '/api/works/import?source=test'
  });
});

test('routes web requests to Next and strips a configured base path only for API requests', async (context) => {
  const api = http.createServer((request, response) => response.end(`api:${request.url}`));
  const web = http.createServer((request, response) => response.end(`web:${request.url}`));
  const apiPort = await listen(api);
  const webPort = await listen(web);
  const gateway = createUnifiedGateway({ apiPort, webPort, basePath: '/books' });
  const gatewayPort = await listen(gateway);
  context.after(async () => Promise.all([close(gateway), close(api), close(web)]));

  const apiResponse = await fetch(`http://127.0.0.1:${gatewayPort}/books/api/health?full=1`);
  const webResponse = await fetch(`http://127.0.0.1:${gatewayPort}/books/library`);

  assert.equal(await apiResponse.text(), 'api:/api/health?full=1');
  assert.equal(await webResponse.text(), 'web:/books/library');
});
