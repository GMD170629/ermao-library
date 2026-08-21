import assert from 'node:assert/strict';
import test from 'node:test';
import { NextRequest } from 'next/server';
import { config, proxy } from '../proxy';

function createRequest(path: string, session?: string): NextRequest {
  const headers = session ? { cookie: `shuku_session=${session}` } : undefined;
  return new NextRequest(new URL(path, 'https://reader.example'), { headers });
}

test('proxy allows public routes without a session', () => {
  const response = proxy(createRequest('/login'));

  assert.equal(response.status, 200);
  assert.equal(response.headers.get('x-middleware-next'), '1');
});

test('proxy allows OPDS Basic authentication requests without a web session', () => {
  const response = proxy(createRequest('/opds/v1.2/catalog'));

  assert.equal(response.status, 200);
  assert.equal(response.headers.get('x-middleware-next'), '1');
});

test('proxy returns the stable unauthorized envelope for protected API routes', async () => {
  const response = proxy(createRequest('/api/books'));

  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), {
    ok: false,
    error: { code: 'UNAUTHORIZED', message: '未登录' }
  });
});

test('proxy redirects protected pages to login and preserves the requested URL', () => {
  const response = proxy(createRequest('/books/book-1?resourceId=resource-1'));

  assert.equal(response.status, 307);
  const location = new URL(response.headers.get('location') ?? '');
  assert.equal(location.pathname, '/login');
  assert.equal(location.searchParams.get('next'), '/books/book-1?resourceId=resource-1');
});

test('proxy allows protected routes with a session', () => {
  const response = proxy(createRequest('/books/book-1', 'session-token'));

  assert.equal(response.status, 200);
  assert.equal(response.headers.get('x-middleware-next'), '1');
});

test('large import uploads bypass proxy request-body buffering', () => {
  assert.deepEqual(config.matcher, [
    '/((?!api/books/import(?:/|$)|.*\\.).*)'
  ]);
});
