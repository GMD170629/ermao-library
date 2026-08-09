import type {
  CancellationToken,
  ServerProfileRepository,
} from './ports';

export type ResetCorruptServerProfilesResult =
  | Readonly<{
      outcome: 'reset';
      deletedFileCount: number;
    }>
  | Readonly<{ outcome: 'not-corrupt' }>
  | Readonly<{ outcome: 'cancelled' }>
  | Readonly<{ outcome: 'failed'; reason: 'storage-unavailable' }>;

export class ResetCorruptServerProfiles {
  constructor(private readonly profiles: ServerProfileRepository) {}

  async execute(
    cancellation?: CancellationToken,
  ): Promise<ResetCorruptServerProfilesResult> {
    if (cancellation?.isCancellationRequested() === true) {
      return { outcome: 'cancelled' };
    }
    const reset = await this.profiles.resetCorrupt(
      cancellation === undefined ? undefined : { cancellation },
    );
    if (!reset.ok) {
      return reset.error.reason === 'cancelled'
        ? { outcome: 'cancelled' }
        : { outcome: 'failed', reason: 'storage-unavailable' };
    }
    return reset.reset
      ? { outcome: 'reset', deletedFileCount: reset.deletedFileCount }
      : { outcome: 'not-corrupt' };
  }
}
