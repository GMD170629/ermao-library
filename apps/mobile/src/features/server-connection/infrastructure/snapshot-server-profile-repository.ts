import {
  PrivateFileSystemError,
  type PrivateFileSystem,
} from '../../../shared/files/private-file-system';
import {
  SnapshotDocumentError,
  SnapshotDocumentStore,
} from '../../../shared/files/snapshot-document-store';
import type { SnapshotOperationCoordinator } from '../../../shared/files/snapshot-operation-coordinator';
import type { IdGenerator } from '../../../shared/lib/runtime';
import { ServerProfileWriteError } from '../application/ports';
import type {
  ActivateServerProfileInput,
  ServerProfileRepository,
  ServerProfileWriteResult,
} from '../application/ports';
import {
  activateServerProfile,
  ServerProfileInvariantError,
  type ServerProfile,
  type ServerProfilesDocumentV1,
} from '../model/server-profile';
import { serverProfilesDocumentCodec } from './server-profile-document-codec';

const SERVER_PROFILES_DIRECTORY = 'server-connection/profiles';

export class SnapshotServerProfileRepository
  implements ServerProfileRepository
{
  private readonly store: SnapshotDocumentStore<ServerProfilesDocumentV1>;

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

  async activateHealthyServer(
    input: ActivateServerProfileInput,
  ): Promise<ServerProfileWriteResult> {
    try {
      const write = await this.store.update((current) => {
        const activated = activateServerProfile(current, input);
        return {
          document: activated.document,
          result: activated.profile,
        };
      });
      return {
        ok: true,
        profile: write.result,
        maintenanceWarningCount: write.maintenanceIssues.length,
        recoveredFromCorruption: write.recoveredFromCorruption,
      };
    } catch (cause: unknown) {
      if (
        cause instanceof ServerProfileInvariantError &&
        cause.code === 'CAPACITY_REACHED'
      ) {
        return {
          ok: false,
          error: new ServerProfileWriteError(
            'capacity-reached',
            cause,
          ),
        };
      }
      if (
        cause instanceof SnapshotDocumentError &&
        cause.code === 'CORRUPT_DOCUMENT'
      ) {
        return {
          ok: false,
          error: new ServerProfileWriteError(
            'corrupt-local-data',
            cause,
          ),
        };
      }
      if (
        cause instanceof PrivateFileSystemError ||
        cause instanceof SnapshotDocumentError
      ) {
        return {
          ok: false,
          error: new ServerProfileWriteError(
            'storage-unavailable',
            cause,
          ),
        };
      }
      throw cause;
    }
  }

  async active(): Promise<ServerProfile | null> {
    const snapshot = await this.store.read();
    if (
      snapshot.status === 'empty' ||
      snapshot.value.activeProfileId === null
    ) {
      return null;
    }
    return (
      snapshot.value.profiles.find(
        (profile) =>
          profile.id === snapshot.value.activeProfileId,
      ) ?? null
    );
  }

  async list(): Promise<readonly ServerProfile[]> {
    const snapshot = await this.store.read();
    return snapshot.status === 'empty' ? [] : snapshot.value.profiles;
  }
}
