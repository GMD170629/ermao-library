import assert from 'node:assert/strict';
import test from 'node:test';
import {
  requestSessionRefreshIfRequired,
  sessionRefreshRequired,
  shouldHandleUnauthorizedPath
} from './auth-session';

test('protected API failures trigger session-expiry handling', () => {
  assert.equal(shouldHandleUnauthorizedPath('/api/auth/me'), true);
  assert.equal(shouldHandleUnauthorizedPath('/api/auth/session/refresh'), true);
  assert.equal(shouldHandleUnauthorizedPath('/api/works'), true);
  assert.equal(shouldHandleUnauthorizedPath('/app/shuku/api/reader/v2/progress'), true);
});

test('expected authentication failures stay on their public forms', () => {
  assert.equal(shouldHandleUnauthorizedPath('/api/auth/login'), false);
  assert.equal(shouldHandleUnauthorizedPath('/api/auth/setup/status'), false);
  assert.equal(shouldHandleUnauthorizedPath('/api/auth/password-reset/confirm'), false);
  assert.equal(shouldHandleUnauthorizedPath('/login'), false);
});

test('session renewal is requested only by the explicit response header', () => {
  assert.equal(sessionRefreshRequired(new Headers()), false);
  assert.equal(sessionRefreshRequired(new Headers({ 'X-Shuku-Session-Refresh': 'required' })), true);
  assert.equal(sessionRefreshRequired(new Headers({ 'X-Shuku-Session-Refresh': 'optional' })), false);
});

test('explicit session renewal is a non-destructive background POST', async () => {
  const calls: Array<{ input: string; init: RequestInit }> = [];
  const controller = new AbortController();
  const fetchSessionRefresh = async (input: string, init: RequestInit) => {
    calls.push({ input, init });
    return new Response(null, { status: 503 });
  };

  await requestSessionRefreshIfRequired(
    new Headers({ 'X-Shuku-Session-Refresh': 'required' }),
    fetchSessionRefresh,
    controller.signal
  );

  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.input, '/api/auth/session/refresh');
  assert.equal(calls[0]?.init.method, 'POST');
  assert.equal(calls[0]?.init.cache, 'no-store');
  assert.equal(calls[0]?.init.credentials, 'same-origin');
  assert.equal(calls[0]?.init.signal, controller.signal);
});

test('session renewal is skipped without the required header', async () => {
  let calls = 0;

  await requestSessionRefreshIfRequired(
    new Headers(),
    async () => {
      calls += 1;
      return new Response(null, { status: 200 });
    },
    new AbortController().signal
  );

  assert.equal(calls, 0);
});

test('session renewal transport failures do not reject cached session validation', async () => {
  await assert.doesNotReject(
    requestSessionRefreshIfRequired(
      new Headers({ 'X-Shuku-Session-Refresh': 'required' }),
      async () => {
        throw new DOMException('aborted', 'AbortError');
      },
      AbortSignal.abort()
    )
  );
});
