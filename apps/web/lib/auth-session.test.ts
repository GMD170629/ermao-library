import assert from 'node:assert/strict';
import test from 'node:test';
import { shouldHandleUnauthorizedPath } from './auth-session';

test('protected API failures trigger session-expiry handling', () => {
  assert.equal(shouldHandleUnauthorizedPath('/api/auth/me'), true);
  assert.equal(shouldHandleUnauthorizedPath('/api/works'), true);
  assert.equal(shouldHandleUnauthorizedPath('/app/shuku/api/reader/v2/progress'), true);
});

test('expected authentication failures stay on their public forms', () => {
  assert.equal(shouldHandleUnauthorizedPath('/api/auth/login'), false);
  assert.equal(shouldHandleUnauthorizedPath('/api/auth/setup/status'), false);
  assert.equal(shouldHandleUnauthorizedPath('/api/auth/password-reset/confirm'), false);
  assert.equal(shouldHandleUnauthorizedPath('/login'), false);
});
