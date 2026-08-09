import {
  type CancellationToken,
  type DeleteServerProfile,
  type DeleteServerProfileResult,
  type LoadServerProfiles,
  type LoadServerProfilesResult,
  type ResetCorruptServerProfiles,
  type ResetCorruptServerProfilesResult,
} from '../../server-connection/public';
import type {
  DeleteProfileFlowResult,
  LoadProfilesFlowResult,
  ResetProfilesFlowResult,
  ServerProfilesFlowFailure,
  ServerProfilesFlowGateway,
} from '../application/server-profiles-controller';

export type ServerProfileFeatureServices = Readonly<{
  deleteServerProfile: Pick<DeleteServerProfile, 'execute'>;
  loadServerProfiles: Pick<LoadServerProfiles, 'execute'>;
  resetCorruptServerProfiles: Pick<ResetCorruptServerProfiles, 'execute'>;
}>;

function failure(
  result:
    | Exclude<DeleteServerProfileResult, Readonly<{ outcome: 'deleted' | 'not-found' }>>
    | Exclude<LoadServerProfilesResult, Readonly<{ outcome: 'loaded' }>>
    | Exclude<ResetCorruptServerProfilesResult, Readonly<{ outcome: 'reset' | 'not-corrupt' }>>,
): ServerProfilesFlowFailure {
  return {
    reason: result.outcome === 'cancelled' ? 'cancelled' : result.reason,
  };
}

export class FeatureServerProfilesGateway
  implements ServerProfilesFlowGateway
{
  constructor(private readonly services: ServerProfileFeatureServices) {}

  async load(
    cancellation: CancellationToken,
  ): Promise<LoadProfilesFlowResult> {
    try {
      const result = await this.services.loadServerProfiles.execute(
        cancellation,
      );
      return result.outcome === 'loaded'
        ? result
        : { outcome: 'failed', failure: failure(result) };
    } catch {
      return {
        outcome: 'failed',
        failure: { reason: 'unexpected-failure' },
      };
    }
  }

  async delete(
    profileId: string,
    cancellation: CancellationToken,
  ): Promise<DeleteProfileFlowResult> {
    try {
      const result = await this.services.deleteServerProfile.execute(
        profileId,
        cancellation,
      );
      if (result.outcome === 'deleted' || result.outcome === 'not-found') {
        return result;
      }
      return { outcome: 'failed', failure: failure(result) };
    } catch {
      return {
        outcome: 'failed',
        failure: { reason: 'unexpected-failure' },
      };
    }
  }

  async reset(
    cancellation: CancellationToken,
  ): Promise<ResetProfilesFlowResult> {
    try {
      const result = await this.services.resetCorruptServerProfiles.execute(
        cancellation,
      );
      if (result.outcome === 'reset' || result.outcome === 'not-corrupt') {
        return { outcome: result.outcome };
      }
      return { outcome: 'failed', failure: failure(result) };
    } catch {
      return {
        outcome: 'failed',
        failure: { reason: 'unexpected-failure' },
      };
    }
  }
}
