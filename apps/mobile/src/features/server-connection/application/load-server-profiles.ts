import type {
  CancellationToken,
  ServerProfilePersistenceWarning,
  ServerProfileRepository,
} from './ports';
import type { ServerProfileCatalog } from '../model/server-profile';

export type LoadServerProfilesResult =
  | Readonly<{
      outcome: 'loaded';
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{ outcome: 'cancelled' }>
  | Readonly<{
      outcome: 'failed';
      reason: 'corrupt-local-data' | 'storage-unavailable';
    }>;

export class LoadServerProfiles {
  constructor(private readonly profiles: ServerProfileRepository) {}

  async execute(
    cancellation?: CancellationToken,
  ): Promise<LoadServerProfilesResult> {
    if (cancellation?.isCancellationRequested() === true) {
      return { outcome: 'cancelled' };
    }
    const loaded = await this.profiles.load(
      cancellation === undefined ? undefined : { cancellation },
    );
    if (cancellation?.isCancellationRequested() === true) {
      return { outcome: 'cancelled' };
    }
    if (!loaded.ok) {
      return loaded.error.reason === 'cancelled'
        ? { outcome: 'cancelled' }
        : { outcome: 'failed', reason: loaded.error.reason };
    }
    return {
      outcome: 'loaded',
      catalog: loaded.catalog,
      warnings: loaded.warnings,
    };
  }
}
