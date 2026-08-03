import http from 'node:http';
import net from 'node:net';
import { pathToFileURL } from 'node:url';

function normalizeBasePath(value) {
  const trimmed = String(value ?? '').trim();
  if (!trimmed || trimmed === '/') return '';
  return `/${trimmed.replace(/^\/+|\/+$/g, '')}`;
}

function backendUpstreamPath(requestUrl, basePath) {
  const parsed = new URL(requestUrl || '/', 'http://gateway.local');
  let pathname = parsed.pathname;
  if (basePath && (pathname === basePath || pathname.startsWith(`${basePath}/`))) {
    pathname = pathname.slice(basePath.length) || '/';
  }
  const isApi = pathname === '/api' || pathname.startsWith('/api/');
  const isOpds = pathname === '/opds' || pathname.startsWith('/opds/');
  if (!isApi && !isOpds) return null;
  return `${pathname}${parsed.search}`;
}

function forwardedHeaders(request, upstreamHost) {
  const headers = { ...request.headers, host: upstreamHost };
  const remoteAddress = request.socket.remoteAddress;
  if (remoteAddress) {
    const previous = request.headers['x-forwarded-for'];
    headers['x-forwarded-for'] = previous ? `${previous}, ${remoteAddress}` : remoteAddress;
  }
  headers['x-forwarded-host'] = request.headers.host ?? '';
  headers['x-forwarded-proto'] = request.socket.encrypted ? 'https' : (request.headers['x-forwarded-proto'] ?? 'http');
  return headers;
}

function proxyHttpRequest(request, response, target) {
  const upstream = http.request({
    hostname: target.hostname,
    port: target.port,
    method: request.method,
    path: target.path,
    headers: forwardedHeaders(request, `${target.hostname}:${target.port}`)
  });

  let responseStarted = false;
  upstream.on('response', (upstreamResponse) => {
    responseStarted = true;
    response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.statusMessage, upstreamResponse.headers);
    upstreamResponse.pipe(response);
    upstreamResponse.on('error', (error) => response.destroy(error));
    response.on('close', () => upstreamResponse.destroy());
  });
  upstream.on('error', (error) => {
    if (responseStarted || response.destroyed) return;
    console.error('gateway.upstream_failed', {
      upstream: `${target.hostname}:${target.port}`,
      code: error.code
    });
    response.writeHead(502, { 'content-type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ ok: false, error: { code: 'UPSTREAM_UNAVAILABLE', message: '服务暂时不可用' } }));
  });
  request.on('aborted', () => upstream.destroy());
  request.on('error', (error) => upstream.destroy(error));
  request.pipe(upstream);
}

function proxyUpgrade(request, socket, head, target) {
  const upstream = net.connect(target.port, target.hostname);
  upstream.on('connect', () => {
    const headers = forwardedHeaders(request, `${target.hostname}:${target.port}`);
    const headerLines = Object.entries(headers).flatMap(([name, value]) => {
      if (Array.isArray(value)) return value.map((entry) => `${name}: ${entry}`);
      return value === undefined ? [] : [`${name}: ${value}`];
    });
    upstream.write(`${request.method ?? 'GET'} ${target.path} HTTP/${request.httpVersion}\r\n${headerLines.join('\r\n')}\r\n\r\n`);
    if (head.length > 0) upstream.write(head);
    socket.pipe(upstream).pipe(socket);
  });
  upstream.on('error', () => socket.destroy());
  socket.on('error', () => upstream.destroy());
  socket.on('close', () => upstream.destroy());
}

export function createUnifiedGateway({
  apiHostname = '127.0.0.1',
  apiPort = 8000,
  webHostname = '127.0.0.1',
  webPort = 3001,
  basePath = ''
} = {}) {
  const normalizedBasePath = normalizeBasePath(basePath);
  const resolveTarget = (requestUrl) => {
    const backendPath = backendUpstreamPath(requestUrl, normalizedBasePath);
    if (backendPath !== null) {
      return { hostname: apiHostname, port: apiPort, path: backendPath };
    }
    return { hostname: webHostname, port: webPort, path: requestUrl || '/' };
  };
  const server = http.createServer((request, response) => {
    proxyHttpRequest(request, response, resolveTarget(request.url));
  });
  server.on('upgrade', (request, socket, head) => {
    proxyUpgrade(request, socket, head, resolveTarget(request.url));
  });
  return server;
}

function integerEnvironmentValue(name, fallback) {
  const parsed = Number.parseInt(process.env[name] ?? '', 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const listenHost = process.env.GATEWAY_HOST || '0.0.0.0';
  const listenPort = integerEnvironmentValue('GATEWAY_PORT', 3000);
  const server = createUnifiedGateway({
    apiHostname: process.env.API_HOST || '127.0.0.1',
    apiPort: integerEnvironmentValue('API_PORT', 8000),
    webHostname: process.env.WEB_UPSTREAM_HOST || '127.0.0.1',
    webPort: integerEnvironmentValue('WEB_UPSTREAM_PORT', 3001),
    basePath: process.env.NEXT_PUBLIC_BASE_PATH || process.env.SHUKU_BASE_PATH || process.env.COOKIE_PATH
  });
  server.listen(listenPort, listenHost, () => {
    process.stdout.write(`Unified gateway listening on http://${listenHost}:${listenPort}\n`);
  });
}
