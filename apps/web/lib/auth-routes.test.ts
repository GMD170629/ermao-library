import assert from 'node:assert/strict';
import test from 'node:test';
import { buildLoginRedirectPath, isPublicAppPath, safePostLoginPath } from './auth-routes';

test('only authentication and offline surfaces are public', () => {
  assert.equal(isPublicAppPath('/login'), true);
  assert.equal(isPublicAppPath('/setup'), true);
  assert.equal(isPublicAppPath('/forgot-password'), true);
  assert.equal(isPublicAppPath('/reset-password'), true);
  assert.equal(isPublicAppPath('/offline'), true);
  assert.equal(isPublicAppPath('/library'), false);
  assert.equal(isPublicAppPath('/reader/volume-1'), false);
});

test('login redirects retain the protected route and its query', () => {
  assert.equal(
    buildLoginRedirectPath('/library', 'status=READING'),
    '/login?next=%2Flibrary%3Fstatus%3DREADING'
  );
});

test('post-login redirects allow local protected paths only', () => {
  assert.equal(safePostLoginPath('/reader/volume-1'), '/reader/volume-1');
  assert.equal(safePostLoginPath('https://example.com'), '/library');
  assert.equal(safePostLoginPath('//example.com'), '/library');
  assert.equal(safePostLoginPath('/\\example.com'), '/library');
  assert.equal(safePostLoginPath('/login'), '/library');
  assert.equal(safePostLoginPath('/setup'), '/library');
});
