import type { Clock } from '../../../shared/lib/runtime';
import type {
  CancellationToken,
  ServerProfilePersistenceWarning,
  ServerProfileRepository,
} from './ports';
import type { ServerProfileCatalog } from '../model/server-profile';

export type DeleteServerProfileResult =
  | Readonly<{
      outcome: 'deleted';
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{ outcome: 'not-found' }>
  | Readonly<{ outcome: 'cancelled' }>
  | Readonly<{
      outcome: 'failed';
      reason: 'corrupt-local-data' | 'storage-unavailable';
    }>;

export class DeleteServerProfile {
  constructor(
    private readonly profiles: ServerProfileRepository,
    private readonly clock: Clock,
  ) {}

  async execute(
    profileId: string,
    cancellation?: CancellationToken,
  ): Promise<DeleteServerProfileResult> {
    if (cancellation?.isCancellationRequested() === true) {
      return { outcome: 'cancelled' };
    }
    const deleted = await this.profiles.deleteProfile(
      { profileId, deletedAtMs: this.clock.nowMs() },
      cancellation === undefined ? undefined : { cancellation },
    );
    if (!deleted.ok) {
      return deleted.error.reason === 'cancelled'
        ? { outcome: 'cancelled' }
        : { outcome: 'failed', reason: deleted.error.reason };
    }
    return deleted.deleted
      ? {
          outcome: 'deleted',
          catalog: deleted.catalog,
          warnings: deleted.warnings,
        }
      : { outcome: 'not-found' };
  }
}
