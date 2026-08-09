import assert from 'node:assert/strict';
import test from 'node:test';

import { validateSignInCredentials } from './sign-in-form';

test('sign-in validation trims a valid email without changing the password', () => {
  assert.deepEqual(
    validateSignInCredentials({
      email: '  Reader@Example.com ',
      password: ' password with spaces ',
    }),
    {
      ok: true,
      credentials: {
        email: 'Reader@Example.com',
        password: ' password with spaces ',
      },
    },
  );
});

test('sign-in validation reports both required fields together', () => {
  assert.deepEqual(
    validateSignInCredentials({ email: '   ', password: '' }),
    {
      ok: false,
      errors: { email: 'required', password: 'required' },
    },
  );
});

test('sign-in validation rejects malformed email and oversized password', () => {
  assert.deepEqual(
    validateSignInCredentials({
      email: 'not-an-email',
      password: 'x'.repeat(129),
    }),
    {
      ok: false,
      errors: { email: 'invalid', password: 'too-long' },
    },
  );
});
