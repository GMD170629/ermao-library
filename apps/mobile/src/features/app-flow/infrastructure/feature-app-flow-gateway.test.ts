import assert from 'node:assert/strict';
import test from 'node:test';

import type { AuthenticatedSession } from '../../identity/public';
import {
  AbortSignalCancellationToken,
  parseServerAddress,
  type ConnectServerResult,
  type LoadServerProfilesResult,
  type SelectServerProfileResult,
  type ServerProfile,
} from '../../server-connection/public';
import {
  FeatureAppFlowGateway,
  type AppFlowFeatureServices,
} from './feature-app-flow-gateway';

function profile(): ServerProfile {
  const parsed = parseServerAddress('https://books.example.com');
  if (!parsed.ok) throw new Error('Test library web address must be valid');
  return {
    id: 'profile-1',
    baseUrl: parsed.baseUrl,
    service: 'ermao-books',
    initialized: true,
    createdAtMs: 1,
    lastVerifiedAtMs: 1,
  };
}

function unusedSession(): AuthenticatedSession {
  return {
    user: {
      id: 'user-1',
      email: 'reader@example.com',
      name: 'Reader',
      role: 'member',
      status: 'active',
      canManageSystem: false,
      canViewManualImports: false,
      authzVersion: 1,
      avatarUrl: null,
      locale: 'en-US',
    },
    authorization: {
      isAdmin: false,
      canManageSystem: false,
      allLibraryScopes: false,
      monitorFolderIds: [],
      canViewManualImports: false,
      authzVersion: 1,
    },
    preferences: { locale: 'en-US' },
  };
}

function services(
  loadResult: LoadServerProfilesResult,
  selectResult: SelectServerProfileResult,
  selectedProfileIds: string[],
): AppFlowFeatureServices {
  return {
    connectServer: {
      execute(): Promise<ConnectServerResult> {
        return Promise.reject(
          new Error('Existing profile recheck must not create a profile'),
        );
      },
    },
    loadServerProfiles: {
      execute(): Promise<LoadServerProfilesResult> {
        return Promise.resolve(loadResult);
      },
    },
    selectServerProfile: {
      execute(profileId): Promise<SelectServerProfileResult> {
        selectedProfileIds.push(profileId);
        return Promise.resolve(selectResult);
      },
    },
    identitySession: {
      login: () =>
        Promise.resolve({
          outcome: 'authenticated' as const,
          session: unusedSession(),
        }),
      logout: () => Promise.resolve({ outcome: 'logged-out' as const }),
      restoreSession: () =>
        Promise.resolve({ outcome: 'unauthenticated' as const }),
    },
  };
}

test('loads the active profile atomically with typed recovery warnings', async () => {
  const activeProfile = profile();
  const warning = {
    kind: 'recovered-older-snapshot' as const,
    rejectedNewerSnapshots: 2,
  };
  const gateway = new FeatureAppFlowGateway(
    services(
      {
        outcome: 'loaded',
        catalog: {
          generation: 1,
          activeProfileId: activeProfile.id,
          profiles: [activeProfile],
          updatedAtMs: 1,
        },
        warnings: [warning],
      },
      { outcome: 'not-found' },
      [],
    ),
  );

  const result = await gateway.loadActiveProfile(
    new AbortSignalCancellationToken(new AbortController().signal),
  );

  assert.deepEqual(result, {
    outcome: 'loaded',
    profile: activeProfile,
    warnings: [warning],
  });
});

test('rechecks an existing profile through selection without reconnecting by URL', async () => {
  const activeProfile = profile();
  const selectedProfileIds: string[] = [];
  const warning = {
    kind: 'maintenance-cleanup-failed' as const,
    issueCount: 1,
  };
  const selected: SelectServerProfileResult = {
    outcome: 'selected',
    profile: activeProfile,
    catalog: {
      generation: 2,
      activeProfileId: activeProfile.id,
      profiles: [activeProfile],
      updatedAtMs: 2,
    },
    warnings: [warning],
  };
  const gateway = new FeatureAppFlowGateway(
    services(
      {
        outcome: 'loaded',
        catalog: {
          generation: 1,
          activeProfileId: activeProfile.id,
          profiles: [activeProfile],
          updatedAtMs: 1,
        },
        warnings: [],
      },
      selected,
      selectedProfileIds,
    ),
  );

  const result = await gateway.recheckProfile(
    activeProfile,
    new AbortSignalCancellationToken(new AbortController().signal),
  );

  assert.deepEqual(selectedProfileIds, [activeProfile.id]);
  assert.deepEqual(result, {
    outcome: 'connected',
    profile: activeProfile,
    warnings: [warning],
  });
});
