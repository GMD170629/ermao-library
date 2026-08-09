import type { ServerBaseUrl } from '../model/server-address';
import type {
  ServerProfile,
  ServerProfileCatalog,
} from '../model/server-profile';

export type ServerUnreachableReason =
  | 'cancelled'
  | 'network'
  | 'timeout';

export interface CancellationToken {
  isCancellationRequested(): boolean;
  subscribe(listener: () => void): () => void;
}

export type ServerHealthProbeResult =
  | Readonly<{ outcome: 'healthy'; initialized: boolean }>
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

export type ServerProfileOperationOptions = Readonly<{
  cancellation?: CancellationToken;
}>;

export type ActivateServerProfileInput = Readonly<{
  baseUrl: ServerBaseUrl;
  initialized: boolean;
  proposedProfileId: string;
  verifiedAtMs: number;
}>;

export type ActivateExistingServerProfileInput = Readonly<{
  profileId: string;
  expectedBaseUrl: string;
  initialized: boolean;
  verifiedAtMs: number;
}>;

export type DeleteServerProfileInput = Readonly<{
  profileId: string;
  deletedAtMs: number;
}>;

export type ServerProfilePersistenceWarning =
  | Readonly<{
      kind: 'recovered-older-snapshot';
      rejectedNewerSnapshots: number;
    }>
  | Readonly<{
      kind: 'maintenance-cleanup-failed';
      issueCount: number;
    }>;

export type ServerProfileRepositoryFailureReason =
  | 'cancelled'
  | 'capacity-reached'
  | 'conflict'
  | 'corrupt-local-data'
  | 'storage-unavailable';

export class ServerProfileRepositoryError<
  Reason extends ServerProfileRepositoryFailureReason =
    ServerProfileRepositoryFailureReason,
> extends Error {
  constructor(
    readonly reason: Reason,
    cause: unknown,
  ) {
    super(`Server profile operation failed: ${reason}`, { cause });
    this.name = 'ServerProfileRepositoryError';
  }
}

export type ServerProfileWriteFailureReason =
  ServerProfileRepositoryFailureReason;

export class ServerProfileWriteError extends ServerProfileRepositoryError<ServerProfileWriteFailureReason> {
  constructor(reason: ServerProfileWriteFailureReason, cause: unknown) {
    super(reason, cause);
    this.name = 'ServerProfileWriteError';
  }
}

type RepositoryFailure<
  Reason extends ServerProfileRepositoryFailureReason =
    ServerProfileRepositoryFailureReason,
> = Readonly<{
  ok: false;
  error: ServerProfileRepositoryError<Reason>;
}>;

export type ServerProfileLoadResult =
  | Readonly<{
      ok: true;
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>
  | RepositoryFailure<
      'cancelled' | 'corrupt-local-data' | 'storage-unavailable'
    >;

export type ServerProfileWriteResult =
  | Readonly<{
      ok: true;
      profile: ServerProfile;
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>
  | RepositoryFailure;

export type ExistingServerProfileWriteResult =
  | (Extract<ServerProfileWriteResult, Readonly<{ ok: true }>> &
      Readonly<{ activated: true }>)
  | Readonly<{ ok: true; activated: false; reason: 'not-found' }>
  | RepositoryFailure<
      'cancelled' | 'conflict' | 'corrupt-local-data' | 'storage-unavailable'
    >;

export type ServerProfileDeleteResult =
  | Readonly<{
      ok: true;
      deleted: true;
      catalog: ServerProfileCatalog;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{ ok: true; deleted: false }>
  | RepositoryFailure<
      'cancelled' | 'corrupt-local-data' | 'storage-unavailable'
    >;

export type ServerProfileResetResult =
  | Readonly<{
      ok: true;
      reset: boolean;
      deletedFileCount: number;
    }>
  | RepositoryFailure<'cancelled' | 'storage-unavailable'>;

export interface ServerProfileRepository {
  load(
    options?: ServerProfileOperationOptions,
  ): Promise<ServerProfileLoadResult>;
  activateHealthyServer(
    input: ActivateServerProfileInput,
    options?: ServerProfileOperationOptions,
  ): Promise<ServerProfileWriteResult>;
  activateExistingHealthyServer(
    input: ActivateExistingServerProfileInput,
    options?: ServerProfileOperationOptions,
  ): Promise<ExistingServerProfileWriteResult>;
  deleteProfile(
    input: DeleteServerProfileInput,
    options?: ServerProfileOperationOptions,
  ): Promise<ServerProfileDeleteResult>;
  resetCorrupt(
    options?: ServerProfileOperationOptions,
  ): Promise<ServerProfileResetResult>;
}
