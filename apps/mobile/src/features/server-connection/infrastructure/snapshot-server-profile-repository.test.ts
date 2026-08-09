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
import {
  MAXIMUM_SERVER_PROFILES,
  ServerProfileInvariantError,
} from '../model/server-profile';
import type { CancellationToken } from '../application/ports';
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
      initialized: true,
      proposedProfileId: `profile-${index}`,
      verifiedAtMs: index,
    });
    assert.equal(result.ok, true);
  }

  const overflow = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://overflow.example'),
    initialized: true,
    proposedProfileId: 'profile-overflow',
    verifiedAtMs: MAXIMUM_SERVER_PROFILES,
  });

  assert.equal(overflow.ok, false);
  if (overflow.ok) {
    assert.fail('Expected capacity exhaustion to fail');
  }
  assert.equal(overflow.error.reason, 'capacity-reached');
});

test('preserves profile identity races as named conflicts', async () => {
  const repository = new SnapshotServerProfileRepository(
    new MemoryPrivateFileSystem(),
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  const created = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://one.example'),
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1,
  });
  assert.equal(created.ok, true);

  const identifierConflict = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://two.example'),
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 2,
  });
  assert.equal(identifierConflict.ok, false);
  if (identifierConflict.ok) {
    assert.fail('Expected duplicate profile identity to conflict');
  }
  assert.equal(identifierConflict.error.reason, 'conflict');
  assert.ok(identifierConflict.error.cause instanceof ServerProfileInvariantError);

  const changedProfile = await repository.activateExistingHealthyServer({
    profileId: 'profile-1',
    expectedBaseUrl: 'https://changed.example',
    initialized: true,
    verifiedAtMs: 3,
  });
  assert.equal(changedProfile.ok, false);
  if (changedProfile.ok) {
    assert.fail('Expected a stale profile base URL to conflict');
  }
  assert.equal(changedProfile.error.reason, 'conflict');
  assert.ok(changedProfile.error.cause instanceof ServerProfileInvariantError);
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
    initialized: true,
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
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1,
  });

  assert.equal(result.ok, false);
  if (result.ok) {
    assert.fail('Expected storage unavailability to fail');
  }
  assert.equal(result.error.reason, 'storage-unavailable');
});

test('loads one atomic catalog and reports recovery from a newer corrupt snapshot', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const repository = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  const first = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://one.example'),
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1,
  });
  assert.equal(first.ok, true);
  const second = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://two.example'),
    initialized: true,
    proposedProfileId: 'profile-2',
    verifiedAtMs: 2,
  });
  assert.equal(second.ok, true);
  const newest = fileSystem
    .fileNames('server-connection/profiles')
    .filter((name) => name.endsWith('.json'))
    .sort()
    .at(-1);
  assert.notEqual(newest, undefined);
  fileSystem.setFile(`server-connection/profiles/${newest}`, '{broken');

  const loaded = await repository.load();

  assert.equal(loaded.ok, true);
  if (!loaded.ok) assert.fail('Expected the older snapshot to load');
  assert.equal(loaded.catalog.generation, 1);
  assert.equal(loaded.catalog.activeProfileId, 'profile-1');
  assert.deepEqual(loaded.warnings, [
    {
      kind: 'recovered-older-snapshot',
      rejectedNewerSnapshots: 1,
    },
  ]);
  assert.deepEqual(await repository.resetCorrupt(), {
    ok: true,
    reset: false,
    deletedFileCount: 0,
  });

  const recoveredWrite = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://one.example'),
    initialized: false,
    proposedProfileId: 'unused-profile-id',
    verifiedAtMs: 3,
  });
  assert.equal(recoveredWrite.ok, true);
  if (!recoveredWrite.ok) {
    assert.fail('Expected a write based on the recovered snapshot');
  }
  assert.deepEqual(recoveredWrite.warnings, [
    {
      kind: 'recovered-older-snapshot',
      rejectedNewerSnapshots: 1,
    },
  ]);
});

test('deleting the active profile never falls back to another profile', async () => {
  const repository = new SnapshotServerProfileRepository(
    new MemoryPrivateFileSystem(),
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://one.example'),
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1,
  });
  await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://two.example'),
    initialized: true,
    proposedProfileId: 'profile-2',
    verifiedAtMs: 2,
  });

  const deleted = await repository.deleteProfile({
    profileId: 'profile-2',
    deletedAtMs: 3,
  });

  assert.equal(deleted.ok, true);
  if (!deleted.ok || !deleted.deleted) {
    assert.fail('Expected the active profile to be deleted');
  }
  assert.equal(deleted.catalog.activeProfileId, null);
  assert.deepEqual(
    deleted.catalog.profiles.map((profile) => profile.id),
    ['profile-1'],
  );
});

test('resets completely corrupt managed files and preserves unrelated files', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  fileSystem.setFile(
    'server-connection/profiles/snapshot-000000000001-broken.json',
    '{broken',
  );
  fileSystem.setFile(
    'server-connection/profiles/.snapshot-000000000002-staged.tmp',
    '{staged',
  );
  fileSystem.setFile('server-connection/profiles/notes.txt', 'keep');
  const repository = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );

  assert.deepEqual(await repository.resetCorrupt(), {
    ok: true,
    reset: true,
    deletedFileCount: 2,
  });
  assert.deepEqual(fileSystem.fileNames('server-connection/profiles'), [
    'notes.txt',
  ]);
  const loaded = await repository.load();
  assert.equal(loaded.ok, true);
  if (!loaded.ok) assert.fail('Expected an empty catalog after reset');
  assert.deepEqual(loaded.catalog.profiles, []);
  assert.equal(loaded.catalog.activeProfileId, null);
});

class MutableCancellationToken implements CancellationToken {
  cancelled = false;

  isCancellationRequested(): boolean {
    return this.cancelled;
  }

  subscribe(): () => void {
    return () => undefined;
  }
}

test('a queued cancelled delete does not cross the commit point', async () => {
  const coordinator = new InProcessSnapshotOperationCoordinator();
  const repository = new SnapshotServerProfileRepository(
    new MemoryPrivateFileSystem(),
    new SequenceIdGenerator(),
    coordinator,
  );
  await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://one.example'),
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1,
  });

  let releaseBlocker: (() => void) | undefined;
  const blocker = coordinator.run(
    'server-connection/profiles',
    () =>
      new Promise<void>((resolve) => {
        releaseBlocker = resolve;
      }),
  );
  await Promise.resolve();
  const cancellation = new MutableCancellationToken();
  const pendingDelete = repository.deleteProfile(
    { profileId: 'profile-1', deletedAtMs: 2 },
    { cancellation },
  );
  cancellation.cancelled = true;
  releaseBlocker?.();
  await blocker;

  const deleted = await pendingDelete;
  assert.equal(deleted.ok, false);
  if (deleted.ok) assert.fail('Expected cancellation to prevent deletion');
  assert.equal(deleted.error.reason, 'cancelled');
  const loaded = await repository.load();
  assert.equal(loaded.ok, true);
  if (!loaded.ok) assert.fail('Expected the profile to remain');
  assert.equal(loaded.catalog.activeProfileId, 'profile-1');
});

test('concurrent connections preserve both profiles in one catalog generation', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  const coordinator = new InProcessSnapshotOperationCoordinator();
  const firstRepository = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    coordinator,
  );
  const secondRepository = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    coordinator,
  );

  const [first, second] = await Promise.all([
    firstRepository.activateHealthyServer({
      baseUrl: serverBaseUrl('https://one.example'),
      initialized: true,
      proposedProfileId: 'profile-1',
      verifiedAtMs: 1,
    }),
    secondRepository.activateHealthyServer({
      baseUrl: serverBaseUrl('https://two.example'),
      initialized: true,
      proposedProfileId: 'profile-2',
      verifiedAtMs: 2,
    }),
  ]);
  assert.equal(first.ok, true);
  assert.equal(second.ok, true);

  const loaded = await firstRepository.load();
  assert.equal(loaded.ok, true);
  if (!loaded.ok) assert.fail('Expected the catalog to load');
  assert.equal(loaded.catalog.generation, 2);
  assert.deepEqual(
    loaded.catalog.profiles.map((profile) => profile.id),
    ['profile-1', 'profile-2'],
  );
  assert.equal(loaded.catalog.activeProfileId, 'profile-2');
});
