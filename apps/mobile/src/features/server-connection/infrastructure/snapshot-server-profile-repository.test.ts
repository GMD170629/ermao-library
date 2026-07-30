import assert from 'node:assert/strict';
import test from 'node:test';

import {
  PrivateFileSystemError,
  type PrivateFileEntry,
} from '../../../shared/files/private-file-system';
import { InProcessSnapshotOperationCoordinator } from '../../../shared/files/snapshot-operation-coordinator';
import {
  MemoryPrivateFileSystem,
  SequenceIdGenerator,
} from '../../../shared/testing/fakes';
import { parseServerAddress } from '../model/server-address';
import { MAXIMUM_SERVER_PROFILES } from '../model/server-profile';
import { SnapshotServerProfileRepository } from './snapshot-server-profile-repository';

function serverBaseUrl(candidate: string) {
  const parsed = parseServerAddress(candidate);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) {
    throw new Error('Test address must be valid');
  }
  return parsed.baseUrl;
}

test('returns a named failure when the profile capacity is reached', async () => {
  const repository = new SnapshotServerProfileRepository(
    new MemoryPrivateFileSystem(),
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );

  for (let index = 0; index < MAXIMUM_SERVER_PROFILES; index += 1) {
    const result = await repository.activateHealthyServer({
      baseUrl: serverBaseUrl(`https://server-${index}.example`),
      proposedProfileId: `profile-${index}`,
      verifiedAtMs: index,
    });
    assert.equal(result.ok, true);
  }

  const overflow = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://overflow.example'),
    proposedProfileId: 'profile-overflow',
    verifiedAtMs: MAXIMUM_SERVER_PROFILES,
  });

  assert.equal(overflow.ok, false);
  if (overflow.ok) {
    assert.fail('Expected capacity exhaustion to fail');
  }
  assert.equal(overflow.error.reason, 'capacity-reached');
});

test('returns a named failure when no valid local snapshot remains', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  fileSystem.setFile(
    'server-connection/profiles/snapshot-000000000001-corrupt.json',
    '{broken',
  );
  const repository = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );

  const result = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://library.example'),
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1,
  });

  assert.equal(result.ok, false);
  if (result.ok) {
    assert.fail('Expected corrupt local data to fail');
  }
  assert.equal(result.error.reason, 'corrupt-local-data');
});

class UnavailablePrivateFileSystem extends MemoryPrivateFileSystem {
  override async list(
    relativeDirectory: string,
  ): Promise<readonly PrivateFileEntry[]> {
    throw new PrivateFileSystemError(
      'list',
      relativeDirectory,
      new Error('Injected storage failure'),
    );
  }
}

test('returns a named failure when private storage is unavailable', async () => {
  const repository = new SnapshotServerProfileRepository(
    new UnavailablePrivateFileSystem(),
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );

  const result = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://library.example'),
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1,
  });

  assert.equal(result.ok, false);
  if (result.ok) {
    assert.fail('Expected storage unavailability to fail');
  }
  assert.equal(result.error.reason, 'storage-unavailable');
});
