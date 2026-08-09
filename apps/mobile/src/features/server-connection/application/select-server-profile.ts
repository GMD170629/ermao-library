import type { Clock } from '../../../shared/lib/runtime';
import type {
  CancellationToken,
  ServerHealthGateway,
  ServerProfilePersistenceWarning,
  ServerProfileRepository,
  ServerUnreachableReason,
} from './ports';
import type {
  ServerProfile,
  ServerProfileCatalog,
} from '../model/server-profile';

export type SelectServerProfileResult =
  | Readonly<{ outcome: 'not-found' }>
  | Readonly<{ outcome: 'cancelled' }>
  | Readonly<{
      outcome: 'unreachable';
      reason: Exclude<ServerUnreachableReason, 'cancelled'>;
    }>
  | Readonly<{ outcome: 'unhealthy'; status: 'error' }>
  | Readonly<{
      outcome: 'incompatible';
      reason: 'invalid-response' | 'unexpected-http-status';
      status: number;
    }>
  | Readonly<{
      outcome: 'failed';
      reason: 'conflict' | 'corrupt-local-data' | 'storage-unavailable';
    }>
  | Readonly<{
      outcome: 'selected';
      profile: ServerProfile;
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>;

function warningKey(warning: ServerProfilePersistenceWarning): string {
  return warning.kind === 'recovered-older-snapshot'
    ? `${warning.kind}:${warning.rejectedNewerSnapshots}`
    : `${warning.kind}:${warning.issueCount}`;
}

function mergeWarnings(
  first: readonly ServerProfilePersistenceWarning[],
  second: readonly ServerProfilePersistenceWarning[],
): readonly ServerProfilePersistenceWarning[] {
  const warnings = new Map<string, ServerProfilePersistenceWarning>();
  for (const warning of [...first, ...second]) {
    warnings.set(warningKey(warning), warning);
  }
  return [...warnings.values()];
}

export class SelectServerProfile {
  constructor(
    private readonly healthGateway: ServerHealthGateway,
    private readonly profiles: ServerProfileRepository,
    private readonly clock: Clock,
  ) {}

  async execute(
    profileId: string,
    cancellation?: CancellationToken,
  ): Promise<SelectServerProfileResult> {
    if (cancellation?.isCancellationRequested() === true) {
      return { outcome: 'cancelled' };
    }
    const loaded = await this.profiles.load(
      cancellation === undefined ? undefined : { cancellation },
    );
    if (!loaded.ok) {
      return loaded.error.reason === 'cancelled'
        ? { outcome: 'cancelled' }
        : { outcome: 'failed', reason: loaded.error.reason };
    }
    const profile = loaded.catalog.profiles.find(
      (candidate) => candidate.id === profileId,
    );
    if (profile === undefined) return { outcome: 'not-found' };
    if (cancellation?.isCancellationRequested() === true) {
      return { outcome: 'cancelled' };
    }

    const health =
      cancellation === undefined
        ? await this.healthGateway.probe(profile.baseUrl)
        : await this.healthGateway.probe(profile.baseUrl, cancellation);
    if (health.outcome !== 'healthy') {
      if (health.outcome === 'unreachable') {
        return health.reason === 'cancelled'
          ? { outcome: 'cancelled' }
          : { outcome: 'unreachable', reason: health.reason };
      }
      return health;
    }
    if (cancellation?.isCancellationRequested() === true) {
      return { outcome: 'cancelled' };
    }

    const selected = await this.profiles.activateExistingHealthyServer(
      {
        profileId: profile.id,
        expectedBaseUrl: profile.baseUrl.value,
        initialized: health.initialized,
        verifiedAtMs: this.clock.nowMs(),
      },
      cancellation === undefined ? undefined : { cancellation },
    );
    if (!selected.ok) {
      return selected.error.reason === 'cancelled'
        ? { outcome: 'cancelled' }
        : { outcome: 'failed', reason: selected.error.reason };
    }
    if (!selected.activated) return { outcome: selected.reason };
    return {
      outcome: 'selected',
      profile: selected.profile,
      catalog: selected.catalog,
      warnings: mergeWarnings(loaded.warnings, selected.warnings),
    };
  }
}
