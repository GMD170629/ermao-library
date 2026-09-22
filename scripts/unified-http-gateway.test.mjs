import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import test from 'node:test';
import { createUnifiedGateway } from './unified-http-gateway.mjs';

const require = createRequire(import.meta.url);
const nextConfig = require('../apps/web/next.config.js');

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

test('records the direct connection failure without request credentials', async (context) => {
  const unavailable = http.createServer();
  const apiPort = await listen(unavailable);
  await close(unavailable);
  const messages = [];
  context.mock.method(console, 'error', (...parts) => messages.push(parts));
  const gateway = createUnifiedGateway({ apiPort });
  const port = await listen(gateway);
  context.after(() => close(gateway));
  const response = await fetch(`http://127.0.0.1:${port}/api/private?token=query-secret`, {
    headers: { authorization: 'Bearer header-secret' }
  });
  assert.equal(response.status, 502);
  const record = messages.find(([event]) => event === 'gateway.request_failed')[1];
  assert.equal(record.stage, 'upstream_request');
  assert.ok(record.requestId);
  assert.equal(record.chain[0].code, 'ECONNREFUSED');
  assert.match(record.chain[0].message, /ECONNREFUSED/);
  assert.ok(record.chain[0].stack);
  assert.doesNotMatch(JSON.stringify(messages), /query-secret|header-secret/);
});

test('records interrupted upstream response after headers were published', async (context) => {
  const messages = [];
  context.mock.method(console, 'error', (...parts) => messages.push(parts));
  const api = http.createServer((_request, response) => {
    response.writeHead(200, { 'content-length': '1000' });
    response.write('part');
    setImmediate(() => response.destroy());
  });
  const apiPort = await listen(api);
  const gateway = createUnifiedGateway({ apiPort });
  const port = await listen(gateway);
  context.after(() => Promise.all([close(gateway), close(api)]));
  await assert.rejects(async () => {
    const response = await fetch(`http://127.0.0.1:${port}/api/stream`);
    await response.arrayBuffer();
  });
  assert.ok(messages.some(([, record]) => record.stage === 'upstream_response'
    && record.chain[0].code === 'ECONNRESET'));
});

test('records the original websocket upgrade failure', async (context) => {
  const unavailable = http.createServer();
  const webPort = await listen(unavailable);
  await close(unavailable);
  const messages = [];
  context.mock.method(console, 'error', (...parts) => messages.push(parts));
  const gateway = createUnifiedGateway({ webPort });
  const port = await listen(gateway);
  context.after(() => close(gateway));
  await new Promise((resolve, reject) => {
    const socket = net.connect(port, '127.0.0.1', () => {
      socket.write('GET /socket HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n');
    });
    socket.on('error', reject);
    socket.on('close', resolve);
  });
  assert.ok(messages.some(([, record]) => record.stage === 'upgrade_upstream'
    && record.chain[0].code === 'ECONNREFUSED'));
});

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

test('routes backend requests to FastAPI and strips a configured base path', async (context) => {
  const api = http.createServer((request, response) => response.end(`api:${request.url}`));
  const web = http.createServer((request, response) => response.end(`web:${request.url}`));
  const apiPort = await listen(api);
  const webPort = await listen(web);
  const gateway = createUnifiedGateway({ apiPort, webPort, basePath: '/books' });
  const gatewayPort = await listen(gateway);
  context.after(async () => Promise.all([close(gateway), close(api), close(web)]));

  const apiResponse = await fetch(`http://127.0.0.1:${gatewayPort}/books/api/health?full=1`);
  const opdsResponse = await fetch(
    `http://127.0.0.1:${gatewayPort}/books/opds/authentication.json`
  );
  const webResponse = await fetch(`http://127.0.0.1:${gatewayPort}/books/library`);

  assert.equal(await apiResponse.text(), 'api:/api/health?full=1');
  assert.equal(await opdsResponse.text(), 'api:/opds/authentication.json');
  assert.equal(await webResponse.text(), 'web:/books/library');
});

test('forwards OPDS methods, credentials, query strings, and bodies unchanged', async (context) => {
  const api = http.createServer((request, response) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({
        method: request.method,
        path: request.url,
        authorization: request.headers.authorization,
        body: Buffer.concat(chunks).toString('utf8')
      }));
    });
  });
  const web = http.createServer((_request, response) => response.end('web'));
  const apiPort = await listen(api);
  const webPort = await listen(web);
  const gateway = createUnifiedGateway({ apiPort, webPort });
  const gatewayPort = await listen(gateway);
  context.after(async () => Promise.all([close(gateway), close(api), close(web)]));

  const body = JSON.stringify({ progression: 0.5 });
  const response = await fetch(
    `http://127.0.0.1:${gatewayPort}/opds/v1.2/volumes/volume-1/progression?source=test`,
    {
      method: 'PUT',
      headers: {
        authorization: 'Basic dXNlcjpwYXNz',
        'content-type': 'application/opds-progression+json'
      },
      body
    }
  );

  assert.deepEqual(await response.json(), {
    method: 'PUT',
    path: '/opds/v1.2/volumes/volume-1/progression?source=test',
    authorization: 'Basic dXNlcjpwYXNz',
    body
  });
});

test('Next development server rewrites API and OPDS requests to FastAPI', async () => {
  const rewrites = await nextConfig.rewrites();

  assert.deepEqual(rewrites.beforeFiles, [
    {
      source: '/api/:path*',
      destination: 'http://127.0.0.1:8000/api/:path*'
    },
    {
      source: '/opds/:path*',
      destination: 'http://127.0.0.1:8000/opds/:path*'
    }
  ]);
});

test('Next development server allows access through every local IPv4 address', () => {
  const localAddresses = Object.values(os.networkInterfaces())
    .flatMap((addresses) => addresses ?? [])
    .filter((address) => address.family === 'IPv4' && !address.internal)
    .map((address) => address.address);

  assert.ok(localAddresses.length > 0);
  for (const address of localAddresses) {
    assert.ok(nextConfig.allowedDevOrigins.includes(address), `${address} is not an allowed dev origin`);
  }
});
