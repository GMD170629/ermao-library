import { useRouter } from 'expo-router';
import {
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

import {
  ServerProfilesScreen,
  type ConnectionIssue,
  type ServerProfilesViewState,
} from '../../server-connection/ui/public';
import { ServerProfilesController } from '../application/server-profiles-controller';
import type { AppFlowCancellationFactory } from '../application/ports';
import {
  FeatureServerProfilesGateway,
  type ServerProfileFeatureServices,
} from '../infrastructure/feature-server-profiles-gateway';
import { useAppFlow } from './app-flow-provider';

export type ServerProfilesFlowScreenProps = Readonly<{
  services: ServerProfileFeatureServices;
  cancellations: AppFlowCancellationFactory;
}>;

function issue(
  reason:
    | 'cancelled'
    | 'corrupt-local-data'
    | 'not-corrupt'
    | 'not-found'
    | 'storage-unavailable'
    | 'unexpected-failure',
): ConnectionIssue {
  switch (reason) {
    case 'cancelled':
      return 'cancelled';
    case 'corrupt-local-data':
      return 'corrupt-storage';
    case 'storage-unavailable':
      return 'storage-unavailable';
    case 'not-corrupt':
    case 'not-found':
    case 'unexpected-failure':
      return 'unknown';
  }
}

function viewState(
  state: ReturnType<ServerProfilesController['getSnapshot']>,
): ServerProfilesViewState {
  if (state.phase === 'loading') return { status: 'loading' };
  if (state.phase === 'failed') {
    return {
      status: 'failed',
      issue: issue(state.failure.reason),
      ...(state.pendingReset
        ? { pendingAction: { type: 'reset' } }
        : {}),
    };
  }
  return {
    status: 'ready',
    profiles: state.catalog.profiles.map((profile) => ({
      id: profile.id,
      active: profile.id === state.catalog.activeProfileId,
      basePath: profile.baseUrl.basePath,
      baseUrl: profile.baseUrl.value,
      initialized: profile.initialized,
      lastVerifiedAtMs: profile.lastVerifiedAtMs,
    })),
    warnings: state.warnings.map((warning) => warning.kind),
    ...(state.pending === undefined
      ? {}
      : {
          pendingAction: {
            type: state.pending.operation,
            profileId: state.pending.profileId,
          },
        }),
  };
}

export function ServerProfilesFlowScreen({
  cancellations,
  services,
}: ServerProfilesFlowScreenProps): ReactNode {
  const router = useRouter();
  const flow = useAppFlow();
  const controller = useMemo(
    () =>
      new ServerProfilesController(
        new FeatureServerProfilesGateway(services),
        {
          profileSelected: flow.selectProfile,
          profileRemoved: flow.profileRemoved,
          profilesReset: flow.profilesReset,
        },
        cancellations,
      ),
    [
      cancellations,
      flow.profileRemoved,
      flow.profilesReset,
      flow.selectProfile,
      services,
    ],
  );
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );

  useEffect(() => {
    void controller.load();
    return () => controller.dispose();
  }, [controller]);

  const screenState = viewState(state);

  return (
    <ServerProfilesScreen
      mode="editable"
      onAddAddress={() => router.push('/address')}
      onAddQr={() => router.push('/scan')}
      onDelete={(profileId) => {
        void controller.delete(profileId);
      }}
      onResetCorrupt={() => {
        void controller.resetCorrupt();
      }}
      onRetry={() => {
        void controller.load();
      }}
      onSelect={(profileId) => {
        void controller.select(profileId);
      }}
      state={screenState}
    />
  );
}
