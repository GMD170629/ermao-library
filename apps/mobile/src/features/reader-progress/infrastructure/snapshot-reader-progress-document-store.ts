import type { IdGenerator } from '../../../shared/lib/runtime';
import type { PrivateFileSystem } from '../../../shared/files/private-file-system';
import { SnapshotDocumentStore } from '../../../shared/files/snapshot-document-store';
import type { SnapshotOperationCoordinator } from '../../../shared/files/snapshot-operation-coordinator';
import type {
  ProgressDocumentMutation,
  ProgressDocumentReadResult,
  ProgressDocumentWriteResult,
  ReaderProgressDocumentStore,
} from '../application/ports';
import {
  isSafeRuntimeId,
  type ProgressConnection,
  type ReaderProgressDocumentV2,
} from '../model/reader-progress';
import { readerProgressDocumentCodec } from './reader-progress-document-codec';

export class SnapshotReaderProgressDocumentStore
  implements ReaderProgressDocumentStore
{
  private readonly stores = new Map<
    string,
    SnapshotDocumentStore<ReaderProgressDocumentV2>
  >();

  constructor(
    private readonly fileSystem: PrivateFileSystem,
    private readonly idGenerator: IdGenerator,
    private readonly operationCoordinator: SnapshotOperationCoordinator,
  ) {}

  async read(
    connection: ProgressConnection,
  ): Promise<ProgressDocumentReadResult> {
    const snapshot = await this.storeFor(connection.profileId).read();
    return snapshot.status === 'empty'
      ? { document: null, recoveredFromCorruption: false }
      : {
          document: snapshot.value,
          recoveredFromCorruption:
            snapshot.recoveredFromCorruption,
        };
  }

  async update<Result>(
    connection: ProgressConnection,
    mutate: (
      current: ReaderProgressDocumentV2 | null,
    ) => ProgressDocumentMutation<Result>,
  ): Promise<ProgressDocumentWriteResult<Result>> {
    const write = await this.storeFor(connection.profileId).update(
      mutate,
    );
    return {
      document: write.value,
      result: write.result,
      recoveredFromCorruption: write.recoveredFromCorruption,
      maintenanceWarningCount: write.maintenanceIssues.length,
    };
  }

  private storeFor(
    profileId: string,
  ): SnapshotDocumentStore<ReaderProgressDocumentV2> {
    if (!isSafeRuntimeId(profileId)) {
      throw new TypeError('Progress profile identifier is not path-safe');
    }
    const existing = this.stores.get(profileId);
    if (existing !== undefined) {
      return existing;
    }

    const store = new SnapshotDocumentStore(
      this.fileSystem,
      `reader-progress/${profileId}`,
      readerProgressDocumentCodec,
      this.idGenerator,
      this.operationCoordinator,
    );
    this.stores.set(profileId, store);
    return store;
  }
}
