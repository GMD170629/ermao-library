import http from 'node:http';
import net from 'node:net';
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';

function safeDiagnosticText(value) {
  let text = String(value ?? '')
    .replace(/(authorization\s*[:=]\s*)(?:bearer|basic)\s+\S+/gi, '$1[redacted]')
    .replace(/((?:token|password|secret|cookie|api[_-]?key)\s*['"]?\s*[:=]\s*['"]?)[^\s,'";]+/gi, '$1[redacted]')
    .replace(/https?:\/\/[^\s'"]+/g, '[url]')
    .replace(/(?<![\w])(?:[A-Za-z]:[\\/]|\/)[^\s'"<>:,)]+/g, '[path]');
  for (const [name, secret] of Object.entries(process.env)) {
    if (secret && secret.length >= 6 && /token|password|secret|cookie|api[_-]?key/i.test(name)) {
      text = text.replaceAll(secret, '[redacted]');
    }
  }
  return text;
}

function diagnosticRecorder() {
  const seen = new WeakSet();
  const requestId = randomUUID();
  return (stage, error) => {
    if (error && typeof error === 'object') {
      if (seen.has(error)) return;
      seen.add(error);
    }
    const chain = [];
    const visited = new Set();
    function append(value) {
      if (!value || visited.has(value)) return;
      visited.add(value);
      chain.push({
        type: value.name ?? typeof value, message: safeDiagnosticText(value.message ?? value),
        code: value.code, errno: value.errno, syscall: value.syscall,
        stack: safeDiagnosticText(value.stack)
      });
      if (value.cause) append(value.cause);
      if (Array.isArray(value.errors)) value.errors.forEach(append);
    }
    append(error);
    console.error('gateway.request_failed', { requestId, stage, chain });
  };
}

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
  // Preserve the public authority for backend Host/Origin validation. The
  // connection target is chosen independently and never comes from Host.
  const headers = { ...request.headers, host: request.headers.host || upstreamHost };
  const remoteAddress = request.socket.remoteAddress;
  if (remoteAddress) {
    const previous = request.headers['x-forwarded-for'];
    headers['x-forwarded-for'] = previous ? `${previous}, ${remoteAddress}` : remoteAddress;
  }
  headers['x-forwarded-host'] = request.headers.host ?? '';
  headers['x-forwarded-proto'] = request.socket.encrypted ? 'https' : (request.headers['x-forwarded-proto'] ?? 'http');
  return headers;
}

function proxyHttpRequest(request, response, target, recordFailure) {
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
    upstreamResponse.on('error', (error) => {
      recordFailure('upstream_response', error);
      response.destroy(error);
    });
    response.on('close', () => upstreamResponse.destroy());
  });
  upstream.on('error', (error) => {
    recordFailure('upstream_request', error);
    if (responseStarted || response.destroyed) return;
    response.writeHead(502, { 'content-type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ ok: false, error: { code: 'UPSTREAM_UNAVAILABLE', message: '服务暂时不可用' } }));
  });
  request.on('aborted', () => upstream.destroy());
  request.on('error', (error) => {
    recordFailure('client_request', error);
    upstream.destroy(error);
  });
  response.on('error', (error) => {
    recordFailure('client_response', error);
    upstream.destroy(error);
  });
  request.pipe(upstream);
}

function proxyUpgrade(request, socket, head, target, recordFailure) {
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
  upstream.on('error', (error) => { recordFailure('upgrade_upstream', error); socket.destroy(); });
  socket.on('error', (error) => { recordFailure('upgrade_client', error); upstream.destroy(); });
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
    const recordFailure = diagnosticRecorder();
    try {
      proxyHttpRequest(request, response, resolveTarget(request.url), recordFailure);
    } catch (error) {
      recordFailure('create_upstream_request', error);
      response.destroy();
    }
  });
  server.on('upgrade', (request, socket, head) => {
    const recordFailure = diagnosticRecorder();
    try {
      proxyUpgrade(request, socket, head, resolveTarget(request.url), recordFailure);
    } catch (error) {
      recordFailure('create_upgrade', error);
      socket.destroy();
    }
  });
  server.on('clientError', (error, socket) => {
    diagnosticRecorder()('parse_request', error);
    const status = error.code === 'HPE_HEADER_OVERFLOW' ? '431 Request Header Fields Too Large' : '400 Bad Request';
    if (socket.writable) socket.end(`HTTP/1.1 ${status}\r\nConnection: close\r\n\r\n`);
    else socket.destroy();
  });
  server.on('error', (error) => diagnosticRecorder()('listen', error));
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
  server.on('error', () => { process.exitCode = 1; });
  server.listen(listenPort, listenHost, () => {
    process.stdout.write(`Unified gateway listening on http://${listenHost}:${listenPort}\n`);
  });
}
