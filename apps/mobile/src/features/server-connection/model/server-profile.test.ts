import assert from 'node:assert/strict';
import test from 'node:test';

import { parseServerAddress } from './server-address';
import { activateServerProfile } from './server-profile';

function serverBaseUrl(candidate: string) {
  const parsed = parseServerAddress(candidate);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) {
    throw new Error('Test address must be valid');
  }
  return parsed.baseUrl;
}

test('keeps profile timestamps monotonic when the device clock moves backwards', () => {
  const firstAddress = serverBaseUrl('http://192.168.1.20:3000');
  const secondAddress = serverBaseUrl('http://192.168.1.21:3000');

  const first = activateServerProfile(null, {
    baseUrl: firstAddress,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1_000,
  });
  const reverified = activateServerProfile(first.document, {
    baseUrl: firstAddress,
    proposedProfileId: 'unused-profile-id',
    verifiedAtMs: 900,
  });
  const second = activateServerProfile(reverified.document, {
    baseUrl: secondAddress,
    proposedProfileId: 'profile-2',
    verifiedAtMs: 800,
  });

  assert.deepEqual(
    {
      reverifiedCreatedAtMs: reverified.profile.createdAtMs,
      reverifiedLastVerifiedAtMs: reverified.profile.lastVerifiedAtMs,
      secondCreatedAtMs: second.profile.createdAtMs,
      secondLastVerifiedAtMs: second.profile.lastVerifiedAtMs,
      updatedAtMs: second.document.updatedAtMs,
    },
    {
      reverifiedCreatedAtMs: 1_000,
      reverifiedLastVerifiedAtMs: 1_000,
      secondCreatedAtMs: 1_000,
      secondLastVerifiedAtMs: 1_000,
      updatedAtMs: 1_000,
    },
  );
  assert.equal(
    second.document.profiles.every(
      (profile) =>
        profile.createdAtMs <= profile.lastVerifiedAtMs &&
        profile.lastVerifiedAtMs <= second.document.updatedAtMs,
    ),
    true,
  );
});
