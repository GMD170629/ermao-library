import type { Clock, IdGenerator } from '../../../shared/lib/runtime';
import type {
  CancellationToken,
  ServerProfilePersistenceWarning,
  ServerHealthGateway,
  ServerProfileRepository,
  ServerProfileWriteFailureReason,
  ServerUnreachableReason,
} from './ports';
import {
  parseServerAddress,
  type ServerAddressErrorCode,
} from '../model/server-address';
import type {
  ServerProfile,
  ServerProfileCatalog,
} from '../model/server-profile';

export type ConnectServerCommand = Readonly<{
  candidate: string;
  source: 'manual' | 'qr';
  cancellation?: CancellationToken;
}>;

export type ConnectServerResult =
  | Readonly<{
      outcome: 'invalid-address';
      code: ServerAddressErrorCode;
    }>
  | Readonly<{
      outcome: 'unreachable';
      reason: ServerUnreachableReason;
    }>
  | Readonly<{ outcome: 'unhealthy'; status: 'error' }>
  | Readonly<{
      outcome: 'incompatible';
      reason: 'invalid-response' | 'unexpected-http-status';
      status: number;
    }>
  | Readonly<{
      outcome: 'profile-save-failed';
      reason: Exclude<ServerProfileWriteFailureReason, 'cancelled'>;
    }>
  | Readonly<{ outcome: 'cancelled' }>
  | Readonly<{
      outcome: 'connected';
      profile: ServerProfile;
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>;

export class ConnectServer {
  constructor(
    private readonly healthGateway: ServerHealthGateway,
    private readonly profiles: ServerProfileRepository,
    private readonly clock: Clock,
    private readonly idGenerator: IdGenerator,
  ) {}

  async execute(
    command: ConnectServerCommand,
  ): Promise<ConnectServerResult> {
    if (command.cancellation?.isCancellationRequested() === true) {
      return { outcome: 'cancelled' };
    }
    const parsed = parseServerAddress(command.candidate);
    if (!parsed.ok) {
      return {
        outcome: 'invalid-address',
        code: parsed.code,
      };
    }

    const health =
      command.cancellation === undefined
        ? await this.healthGateway.probe(parsed.baseUrl)
        : await this.healthGateway.probe(
            parsed.baseUrl,
            command.cancellation,
          );
    if (health.outcome !== 'healthy') {
      if (
        health.outcome === 'unreachable' &&
        health.reason === 'cancelled'
      ) {
        return { outcome: 'cancelled' };
      }
      return health;
    }

    if (command.cancellation?.isCancellationRequested() === true) {
      return { outcome: 'cancelled' };
    }

    const persisted = await this.profiles.activateHealthyServer(
      {
        baseUrl: parsed.baseUrl,
        initialized: health.initialized,
        proposedProfileId: this.idGenerator.nextId(),
        verifiedAtMs: this.clock.nowMs(),
      },
      command.cancellation === undefined
        ? undefined
        : { cancellation: command.cancellation },
    );
    if (!persisted.ok) {
      if (persisted.error.reason === 'cancelled') {
        return { outcome: 'cancelled' };
      }
      return {
        outcome: 'profile-save-failed',
        reason: persisted.error.reason,
      };
    }
    return {
      outcome: 'connected',
      profile: persisted.profile,
      catalog: persisted.catalog,
      warnings: persisted.warnings,
    };
  }
}
