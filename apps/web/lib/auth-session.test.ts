import assert from 'node:assert/strict';
import test from 'node:test';
import { shouldHandleUnauthorizedPath } from './auth-session';

test('protected API failures trigger session-expiry handling', () => {
  assert.equal(shouldHandleUnauthorizedPath('/api/v2/account'), true);
  assert.equal(shouldHandleUnauthorizedPath('/api/v2/catalog/works'), true);
  assert.equal(shouldHandleUnauthorizedPath('/app/shuku/api/v2/reading/progress'), true);
});

test('expected authentication failures stay on their public forms', () => {
  assert.equal(shouldHandleUnauthorizedPath('/api/v2/auth/login'), false);
  assert.equal(shouldHandleUnauthorizedPath('/api/v2/auth/setup/status'), false);
  assert.equal(shouldHandleUnauthorizedPath('/api/v2/auth/password-reset/confirm'), false);
  assert.equal(shouldHandleUnauthorizedPath('/login'), false);
});
