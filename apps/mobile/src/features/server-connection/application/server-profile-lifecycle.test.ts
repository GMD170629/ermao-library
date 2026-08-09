import assert from 'node:assert/strict';
import test from 'node:test';

import { InProcessSnapshotOperationCoordinator } from '../../../shared/files/snapshot-operation-coordinator';
import {
  IncrementingClock,
  MemoryPrivateFileSystem,
  SequenceIdGenerator,
} from '../../../shared/testing/fakes';
import { SnapshotServerProfileRepository } from '../infrastructure/snapshot-server-profile-repository';
import { parseServerAddress } from '../model/server-address';
import { DeleteServerProfile } from './delete-server-profile';
import { LoadServerProfiles } from './load-server-profiles';
import { ResetCorruptServerProfiles } from './reset-corrupt-server-profiles';
import { SelectServerProfile } from './select-server-profile';
import type { ServerHealthGateway } from './ports';

function serverBaseUrl(candidate: string) {
  const parsed = parseServerAddress(candidate);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) assert.fail('Expected a valid library web address');
  return parsed.baseUrl;
}

test('selecting a profile does not resurrect it after concurrent deletion', async () => {
  const repository = new SnapshotServerProfileRepository(
    new MemoryPrivateFileSystem(),
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  const created = await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://books.example/shuku'),
    initialized: true,
    proposedProfileId: 'profile-1',
    verifiedAtMs: 1,
  });
  assert.equal(created.ok, true);

  let releaseHealth: (() => void) | undefined;
  let markHealthStarted: (() => void) | undefined;
  const healthStarted = new Promise<void>((resolve) => {
    markHealthStarted = resolve;
  });
  const healthGateway: ServerHealthGateway = {
    async probe() {
      markHealthStarted?.();
      await new Promise<void>((resolve) => {
        releaseHealth = resolve;
      });
      return { outcome: 'healthy', initialized: true };
    },
  };
  const select = new SelectServerProfile(
    healthGateway,
    repository,
    new IncrementingClock(10),
  );
  const pendingSelection = select.execute('profile-1');
  await healthStarted;

  const deleted = await new DeleteServerProfile(
    repository,
    new IncrementingClock(5),
  ).execute('profile-1');
  assert.equal(deleted.outcome, 'deleted');
  releaseHealth?.();

  assert.deepEqual(await pendingSelection, { outcome: 'not-found' });
  const loaded = await repository.load();
  assert.equal(loaded.ok, true);
  if (!loaded.ok) assert.fail('Expected the catalog to load');
  assert.deepEqual(loaded.catalog.profiles, []);
  assert.equal(loaded.catalog.activeProfileId, null);
});

test('selecting an existing profile rechecks health before activation', async () => {
  const repository = new SnapshotServerProfileRepository(
    new MemoryPrivateFileSystem(),
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );
  await repository.activateHealthyServer({
    baseUrl: serverBaseUrl('https://one.example/base'),
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
  let probedUrl: string | null = null;
  const selected = await new SelectServerProfile(
    {
      async probe(baseUrl) {
        probedUrl = baseUrl.value;
        return { outcome: 'healthy', initialized: false };
      },
    },
    repository,
    new IncrementingClock(10),
  ).execute('profile-1');

  assert.equal(probedUrl, 'https://one.example/base');
  assert.equal(selected.outcome, 'selected');
  if (selected.outcome !== 'selected') {
    assert.fail('Expected the existing profile to be selected');
  }
  assert.equal(selected.profile.initialized, false);
  assert.equal(selected.catalog.activeProfileId, 'profile-1');
});

test('load and reset expose a complete-corruption recovery flow', async () => {
  const fileSystem = new MemoryPrivateFileSystem();
  fileSystem.setFile(
    'server-connection/profiles/snapshot-000000000001-broken.json',
    '{broken',
  );
  const repository = new SnapshotServerProfileRepository(
    fileSystem,
    new SequenceIdGenerator(),
    new InProcessSnapshotOperationCoordinator(),
  );

  assert.deepEqual(await new LoadServerProfiles(repository).execute(), {
    outcome: 'failed',
    reason: 'corrupt-local-data',
  });
  assert.deepEqual(
    await new ResetCorruptServerProfiles(repository).execute(),
    { outcome: 'reset', deletedFileCount: 1 },
  );
  const loaded = await new LoadServerProfiles(repository).execute();
  assert.equal(loaded.outcome, 'loaded');
  if (loaded.outcome !== 'loaded') {
    assert.fail('Expected the reset catalog to load');
  }
  assert.deepEqual(loaded.catalog.profiles, []);
  assert.equal(loaded.catalog.activeProfileId, null);
});
