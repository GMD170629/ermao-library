#!/usr/bin/env node

const baseUrl = process.env.ACCEPTANCE_BASE_URL ?? 'http://127.0.0.1:3000';
const email = process.env.ACCEPTANCE_EMAIL ?? 'acceptance@example.com';
const password = process.env.ACCEPTANCE_PASSWORD ?? 'acceptance-password-123';
let cookie = '';

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

async function request(path, init = {}) {
  const headers = new Headers(init.headers ?? {});
  if (cookie) headers.set('cookie', cookie);
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers });
  const setCookie = response.headers.get('set-cookie');
  if (setCookie) cookie = setCookie.split(';')[0];
  return response;
}

async function json(path, init) {
  const response = await request(path, init);
  const payload = await response.json().catch(() => null);
  expect(response.ok && payload?.ok, `${path} failed with ${response.status}`);
  return payload.data;
}

async function main() {
  const setup = await json('/api/auth/setup/status');
  if (setup.initialized) {
    await json('/api/auth/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
  } else {
    await json('/api/auth/setup', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
  }

  for (const path of ['/', '/library', '/import-tasks', '/settings']) {
    const response = await request(path);
    const text = await response.text();
    expect(response.ok, `${path} returned ${response.status}`);
    expect(!text.includes(`/scan${'-tasks'}`), `${path} still links removed task route`);
    expect(!text.includes(`/api/library${'-paths'}`), `${path} still links removed folder API`);
  }

  await json('/api/monitor-folders');
  await json('/api/import-tasks');
  const books = await json('/api/works?pageSize=5');
  expect(Array.isArray(books.books), 'books payload missing books array');
  console.log('[acceptance] import system smoke check passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
