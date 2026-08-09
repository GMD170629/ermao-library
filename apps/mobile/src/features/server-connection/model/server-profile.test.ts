import assert from 'node:assert/strict';
import test from 'node:test';

import { parseServerAddress } from './server-address';
import {
  activateExistingServerProfile,
  activateServerProfile,
  deleteServerProfile,
  serverProfileCatalog,
} from './server-profile';

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
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1_000,
  });
  const reverified = activateServerProfile(first.document, {
    baseUrl: firstAddress,
    initialized: false,
    proposedProfileId: 'unused-profile-id',
    verifiedAtMs: 900,
  });
  const second = activateServerProfile(reverified.document, {
    baseUrl: secondAddress,
    initialized: true,
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
  assert.equal(reverified.profile.initialized, false);
});

test('deleting the active profile leaves the remaining catalog inactive', () => {
  const first = activateServerProfile(null, {
    baseUrl: serverBaseUrl('https://one.example'),
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 10,
  });
  const second = activateServerProfile(first.document, {
    baseUrl: serverBaseUrl('https://two.example'),
    initialized: true,
    proposedProfileId: 'profile-2',
    verifiedAtMs: 20,
  });

  const deleted = deleteServerProfile(second.document, {
    profileId: 'profile-2',
    deletedAtMs: 21,
  });

  assert.equal(deleted.activeProfileId, null);
  assert.deepEqual(
    deleted.profiles.map((profile) => profile.id),
    ['profile-1'],
  );
  assert.deepEqual(serverProfileCatalog(deleted), {
    generation: 3,
    activeProfileId: null,
    profiles: [first.profile],
    updatedAtMs: 21,
  });
});

test('selecting an existing profile refuses a stale base URL', () => {
  const created = activateServerProfile(null, {
    baseUrl: serverBaseUrl('https://books.example/shuku'),
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 10,
  });

  assert.throws(
    () =>
      activateExistingServerProfile(created.document, {
        profileId: 'profile-1',
        expectedBaseUrl: 'https://other.example',
        initialized: true,
        verifiedAtMs: 11,
      }),
    (error: unknown) =>
      error instanceof Error && error.message.includes('changed'),
  );
});
