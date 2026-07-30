import type { Clock, IdGenerator } from '../../../shared/lib/runtime';
import type {
  CancellationToken,
  ServerHealthGateway,
  ServerProfileRepository,
  ServerProfileWriteFailureReason,
  ServerUnreachableReason,
} from './ports';
import {
  parseServerAddress,
  type ServerAddressErrorCode,
} from '../model/server-address';
import type { ServerProfile } from '../model/server-profile';

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
      reason: ServerProfileWriteFailureReason;
    }>
  | Readonly<{
      outcome: 'connected';
      profile: ServerProfile;
      recoveredFromCorruption: boolean;
      maintenanceWarningCount: number;
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
      return health;
    }

    const persisted = await this.profiles.activateHealthyServer({
      baseUrl: parsed.baseUrl,
      proposedProfileId: this.idGenerator.nextId(),
      verifiedAtMs: this.clock.nowMs(),
    });
    if (!persisted.ok) {
      return {
        outcome: 'profile-save-failed',
        reason: persisted.error.reason,
      };
    }
    return {
      outcome: 'connected',
      profile: persisted.profile,
      recoveredFromCorruption: persisted.recoveredFromCorruption,
      maintenanceWarningCount: persisted.maintenanceWarningCount,
    };
  }
}
