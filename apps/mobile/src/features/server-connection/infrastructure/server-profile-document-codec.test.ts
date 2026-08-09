import assert from 'node:assert/strict';
import test from 'node:test';

import { serverProfilesDocumentCodec } from './server-profile-document-codec';

const currentDocument = {
  format: 'shuku.server-profiles',
  schemaVersion: 2,
  generation: 1,
  activeProfileId: 'profile-1',
  profiles: [
    {
      id: 'profile-1',
      baseUrl: 'https://books.example.com/shuku',
      service: 'ermao-books',
      initialized: true,
      createdAtMs: 1,
      lastVerifiedAtMs: 1,
    },
  ],
  updatedAtMs: 1,
} as const;

test('decodes only the current setup-aware server profile schema', () => {
  const decoded = serverProfilesDocumentCodec.decode(currentDocument);
  assert.equal(decoded.ok, true);
  if (!decoded.ok) {
    assert.fail('Expected the current server profile schema to decode');
  }
  assert.equal(decoded.value.profiles[0]?.initialized, true);
});

test('does not retain the former server profile schema', () => {
  const decoded = serverProfilesDocumentCodec.decode({
    ...currentDocument,
    schemaVersion: 1,
    profiles: currentDocument.profiles.map(({ initialized: _removed, ...profile }) =>
      profile,
    ),
  });
  assert.deepEqual(decoded, {
    ok: false,
    reason: 'INVALID_SERVER_PROFILES_DOCUMENT',
  });
});

test('rejects future schemas and unknown document or profile fields', () => {
  for (const candidate of [
    { ...currentDocument, schemaVersion: 3 },
    { ...currentDocument, selectedProfileId: 'profile-1' },
    {
      ...currentDocument,
      profiles: currentDocument.profiles.map((profile) => ({
        ...profile,
        legacyServerId: 'server-1',
      })),
    },
  ]) {
    assert.deepEqual(serverProfilesDocumentCodec.decode(candidate), {
      ok: false,
      reason: 'INVALID_SERVER_PROFILES_DOCUMENT',
    });
  }
});
