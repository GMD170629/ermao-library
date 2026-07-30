import type { ServerBaseUrl } from '../model/server-address';
import type { ServerProfile } from '../model/server-profile';

export type ServerUnreachableReason =
  | 'cancelled'
  | 'network'
  | 'timeout';

export interface CancellationToken {
  isCancellationRequested(): boolean;
  subscribe(listener: () => void): () => void;
}

export type ServerHealthProbeResult =
  | Readonly<{ outcome: 'healthy' }>
  | Readonly<{ outcome: 'unhealthy'; status: 'error' }>
  | Readonly<{
      outcome: 'unreachable';
      reason: ServerUnreachableReason;
    }>
  | Readonly<{
      outcome: 'incompatible';
      reason: 'invalid-response' | 'unexpected-http-status';
      status: number;
    }>;

export interface ServerHealthGateway {
  probe(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<ServerHealthProbeResult>;
}

export type ActivateServerProfileInput = Readonly<{
  baseUrl: ServerBaseUrl;
  proposedProfileId: string;
  verifiedAtMs: number;
}>;

export type ServerProfileWriteFailureReason =
  | 'capacity-reached'
  | 'corrupt-local-data'
  | 'storage-unavailable';

export class ServerProfileWriteError extends Error {
  constructor(
    readonly reason: ServerProfileWriteFailureReason,
    cause: unknown,
  ) {
    super(`Server profile write failed: ${reason}`, { cause });
    this.name = 'ServerProfileWriteError';
  }
}

export type ServerProfileWriteResult =
  | Readonly<{
      ok: true;
      profile: ServerProfile;
      maintenanceWarningCount: number;
      recoveredFromCorruption: boolean;
    }>
  | Readonly<{
      ok: false;
      error: ServerProfileWriteError;
    }>;

export interface ServerProfileRepository {
  activateHealthyServer(
    input: ActivateServerProfileInput,
  ): Promise<ServerProfileWriteResult>;
  active(): Promise<ServerProfile | null>;
  list(): Promise<readonly ServerProfile[]>;
}