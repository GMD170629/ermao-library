#!/usr/bin/env node

const baseUrl = (process.env.ACCEPTANCE_BASE_URL ?? 'http://127.0.0.1:3000').replace(/\/$/, '');
const email = process.env.ACCEPTANCE_EMAIL ?? 'acceptance@example.com';
const password = process.env.ACCEPTANCE_PASSWORD ?? 'acceptance-password-123';
let cookie = '';

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

async function request(path, init = {}) {
  const headers = new Headers(init.headers ?? {});
  if (cookie) headers.set('cookie', cookie);
  if (init.method && init.method !== 'GET' && init.method !== 'HEAD') {
    headers.set('origin', new URL(baseUrl).origin);
  }
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers });
  const setCookie = response.headers.get('set-cookie');
  if (setCookie) cookie = setCookie.split(';')[0];
  return response;
}

async function json(path, init) {
  const response = await request(path, init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(
      `${path} failed with ${response.status}: ${payload?.detail ?? response.statusText}`
    );
  }
  return payload;
}

async function main() {
  const setup = await json('/api/v2/auth/setup/status');
  expect(typeof setup.required === 'boolean', 'setup response is not the appv2 contract');
  if (setup.required) {
    await json('/api/v2/auth/setup', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        email,
        displayName: 'Acceptance',
        password,
        locale: 'en-US'
      })
    });
  } else {
    await json('/api/v2/auth/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
  }

  const account = await json('/api/v2/account');
  expect(account.email === email, 'authenticated account does not match acceptance credentials');

  const [folders, imports, works, queues, openapi] = await Promise.all([
    json('/api/v2/ingestion/folders'),
    json('/api/v2/ingestion/imports'),
    json('/api/v2/catalog/works?pageSize=5'),
    json('/api/v2/operations/queues'),
    json('/api/v2/openapi.json')
  ]);
  for (const [name, resource] of Object.entries({ folders, imports, works, queues })) {
    expect(
      Array.isArray(resource.items)
        && Number.isInteger(resource.page)
        && Number.isInteger(resource.pageSize)
        && Number.isInteger(resource.total),
      `${name} is not a standard appv2 page resource`
    );
  }
  expect(openapi.info?.version === '0.4.0', 'OpenAPI does not report v0.4.0');
  const paths = Object.keys(openapi.paths ?? {});
  expect(paths.length > 0, 'OpenAPI does not expose any routes');
  expect(
    paths.every((path) => path.startsWith('/api/v2/')),
    `OpenAPI exposes a non-v2 route: ${paths.filter((path) => !path.startsWith('/api/v2/')).join(', ')}`
  );

  for (const path of ['/', '/library', '/import-tasks', '/settings', '/organize']) {
    const response = await request(path);
    const text = await response.text();
    expect(response.ok, `${path} returned ${response.status}`);
    expect(!text.includes('/api/monitor-folders'), `${path} still contains a legacy API URL`);
    expect(!text.includes('/api/import-tasks'), `${path} still contains a legacy API URL`);
  }

  for (const legacyPath of ['/api/health', '/api/works', '/api/import-tasks']) {
    const response = await request(legacyPath);
    expect(response.status === 404, `${legacyPath} is still served with ${response.status}`);
  }

  console.log('[acceptance] appv2 account, pagination, OpenAPI, Web, and legacy-cutover checks passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
