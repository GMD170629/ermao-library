import assert from 'node:assert/strict';
import test from 'node:test';
import { accountAuthorizationVersion } from './account-authorization';

test('authorization namespace is independent of scope ordering', () => {
  assert.equal(
    accountAuthorizationVersion({ role: 'admin', scopes: ['reading:write', 'catalog:read'] }),
    accountAuthorizationVersion({ role: 'admin', scopes: ['catalog:read', 'reading:write'] })
  );
});

test('authorization namespace changes with role or effective scopes', () => {
  const current = accountAuthorizationVersion({ role: 'user', scopes: ['catalog:read'] });
  assert.notEqual(current, accountAuthorizationVersion({ role: 'admin', scopes: ['catalog:read'] }));
  assert.notEqual(current, accountAuthorizationVersion({ role: 'user', scopes: ['catalog:read', 'reading:write'] }));
});
