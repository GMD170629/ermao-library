import {
  PrivateFileSystemError,
  type PrivateFileSystem,
} from '../../../shared/files/private-file-system';
import {
  SnapshotDocumentError,
  SnapshotDocumentStore,
  type SnapshotReadResult,
  type SnapshotUpdateResult,
} from '../../../shared/files/snapshot-document-store';
import type { SnapshotOperationCoordinator } from '../../../shared/files/snapshot-operation-coordinator';
import type { IdGenerator } from '../../../shared/lib/runtime';
import {
  ServerProfileRepositoryError,
  type ActivateExistingServerProfileInput,
  type ActivateServerProfileInput,
  type DeleteServerProfileInput,
  type ExistingServerProfileWriteResult,
  type ServerProfileDeleteResult,
  type ServerProfileLoadResult,
  type ServerProfileOperationOptions,
  type ServerProfilePersistenceWarning,
  type ServerProfileRepository,
  type ServerProfileRepositoryFailureReason,
  type ServerProfileResetResult,
  type ServerProfileWriteResult,
} from '../application/ports';
import {
  activateExistingServerProfile,
  activateServerProfile,
  deleteServerProfile,
  serverProfileCatalog,
  ServerProfileInvariantError,
  type ServerProfilesDocument,
} from '../model/server-profile';
import { serverProfilesDocumentCodec } from './server-profile-document-codec';

const SERVER_PROFILES_DIRECTORY = 'server-connection/profiles';

class ServerProfileOperationCancelled extends Error {
  constructor() {
    super('Server profile operation was cancelled before its commit point');
    this.name = 'ServerProfileOperationCancelled';
  }
}

function assertNotCancelled(options?: ServerProfileOperationOptions): void {
  if (options?.cancellation?.isCancellationRequested() === true) {
    throw new ServerProfileOperationCancelled();
  }
}

function recoveryWarnings(
  snapshot: SnapshotReadResult<ServerProfilesDocument>,
): readonly ServerProfilePersistenceWarning[] {
  return snapshot.status === 'loaded' && snapshot.recoveredFromCorruption
    ? [
        {
          kind: 'recovered-older-snapshot',
          rejectedNewerSnapshots: snapshot.rejectedNewerSnapshots,
        },
      ]
    : [];
}

function writeWarnings<Result>(
  write: SnapshotUpdateResult<ServerProfilesDocument, Result>,
): readonly ServerProfilePersistenceWarning[] {
  const warnings: ServerProfilePersistenceWarning[] = [];
  if (write.recoveredFromCorruption) {
    warnings.push({
      kind: 'recovered-older-snapshot',
      rejectedNewerSnapshots: write.rejectedNewerSnapshots,
    });
  }
  if (write.maintenanceIssues.length > 0) {
    warnings.push({
      kind: 'maintenance-cleanup-failed',
      issueCount: write.maintenanceIssues.length,
    });
  }
  return warnings;
}

function repositoryError(
  cause: unknown,
): ServerProfileRepositoryError<
  'cancelled' | 'corrupt-local-data' | 'storage-unavailable'
> | null {
  if (cause instanceof ServerProfileOperationCancelled) {
    return new ServerProfileRepositoryError('cancelled', cause);
  }
  if (
    cause instanceof SnapshotDocumentError &&
    cause.code === 'CORRUPT_DOCUMENT'
  ) {
    return new ServerProfileRepositoryError('corrupt-local-data', cause);
  }
  if (
    cause instanceof PrivateFileSystemError ||
    cause instanceof SnapshotDocumentError
  ) {
    return new ServerProfileRepositoryError('storage-unavailable', cause);
  }
  return null;
}

function failed<Reason extends ServerProfileRepositoryFailureReason>(
  error: ServerProfileRepositoryError<Reason>,
): Readonly<{ ok: false; error: ServerProfileRepositoryError<Reason> }> {
  return { ok: false, error };
}

export class SnapshotServerProfileRepository
  implements ServerProfileRepository
{
  private readonly store: SnapshotDocumentStore<ServerProfilesDocument>;

  constructor(
    fileSystem: PrivateFileSystem,
    idGenerator: IdGenerator,
    operationCoordinator: SnapshotOperationCoordinator,
  ) {
    this.store = new SnapshotDocumentStore(
      fileSystem,
      SERVER_PROFILES_DIRECTORY,
      serverProfilesDocumentCodec,
      idGenerator,
      operationCoordinator,
    );
  }

  async load(
    options?: ServerProfileOperationOptions,
  ): Promise<ServerProfileLoadResult> {
    try {
      assertNotCancelled(options);
      const snapshot = await this.store.read();
      assertNotCancelled(options);
      return {
        ok: true,
        catalog: serverProfileCatalog(
          snapshot.status === 'loaded' ? snapshot.value : null,
        ),
        warnings: recoveryWarnings(snapshot),
      };
    } catch (cause: unknown) {
      const error = repositoryError(cause);
      if (error === null) throw cause;
      return failed(error);
    }
  }

  async activateHealthyServer(
    input: ActivateServerProfileInput,
    options?: ServerProfileOperationOptions,
  ): Promise<ServerProfileWriteResult> {
    try {
      const write = await this.store.update((current) => {
        assertNotCancelled(options);
        const activated = activateServerProfile(current, input);
        return {
          document: activated.document,
          result: activated.profile,
        };
      });
      return {
        ok: true,
        profile: write.result,
        catalog: serverProfileCatalog(write.value),
        warnings: writeWarnings(write),
      };
    } catch (cause: unknown) {
      if (
        cause instanceof ServerProfileInvariantError &&
        cause.code === 'CAPACITY_REACHED'
      ) {
        return failed(
          new ServerProfileRepositoryError('capacity-reached', cause),
        );
      }
      if (
        cause instanceof ServerProfileInvariantError &&
        cause.code === 'PROFILE_ID_CONFLICT'
      ) {
        return failed(new ServerProfileRepositoryError('conflict', cause));
      }
      const error = repositoryError(cause);
      if (error === null) throw cause;
      return failed(error);
    }
  }

  async activateExistingHealthyServer(
    input: ActivateExistingServerProfileInput,
    options?: ServerProfileOperationOptions,
  ): Promise<ExistingServerProfileWriteResult> {
    try {
      const write = await this.store.update((current) => {
        assertNotCancelled(options);
        const activated = activateExistingServerProfile(current, input);
        return {
          document: activated.document,
          result: activated,
        };
      });
      return {
        ok: true,
        activated: true,
        profile: write.result.profile,
        catalog: serverProfileCatalog(write.value),
        warnings: writeWarnings(write),
      };
    } catch (cause: unknown) {
      if (
        cause instanceof ServerProfileInvariantError &&
        cause.code === 'PROFILE_NOT_FOUND'
      ) {
        return { ok: true, activated: false, reason: 'not-found' };
      }
      if (
        cause instanceof ServerProfileInvariantError &&
        cause.code === 'PROFILE_CHANGED'
      ) {
        return failed(new ServerProfileRepositoryError('conflict', cause));
      }
      const error = repositoryError(cause);
      if (error === null) throw cause;
      return failed(error);
    }
  }

  async deleteProfile(
    input: DeleteServerProfileInput,
    options?: ServerProfileOperationOptions,
  ): Promise<ServerProfileDeleteResult> {
    try {
      const write = await this.store.update((current) => {
        assertNotCancelled(options);
        return {
          document: deleteServerProfile(current, input),
          result: true,
        };
      });
      return {
        ok: true,
        deleted: true,
        catalog: serverProfileCatalog(write.value),
        warnings: writeWarnings(write),
      };
    } catch (cause: unknown) {
      if (
        cause instanceof ServerProfileInvariantError &&
        cause.code === 'PROFILE_NOT_FOUND'
      ) {
        return { ok: true, deleted: false };
      }
      const error = repositoryError(cause);
      if (error === null) throw cause;
      return failed(error);
    }
  }

  async resetCorrupt(
    options?: ServerProfileOperationOptions,
  ): Promise<ServerProfileResetResult> {
    try {
      assertNotCancelled(options);
      const reset = await this.store.resetCorrupt(() =>
        assertNotCancelled(options),
      );
      return {
        ok: true,
        reset: reset.status === 'reset',
        deletedFileCount: reset.deletedFileCount,
      };
    } catch (cause: unknown) {
      const error = repositoryError(cause);
      if (error === null || error.reason === 'corrupt-local-data') throw cause;
      return failed(new ServerProfileRepositoryError(error.reason, cause));
    }
  }
}
