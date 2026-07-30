import {
  LoadReaderProgress,
  SaveReaderProgress,
  SnapshotReaderProgressDocumentStore,
} from '../features/reader-progress/public';
import {
  ConnectServer,
  ServerHealthClient,
  SnapshotServerProfileRepository,
  type ServerProfileRepository,
} from '../features/server-connection/public';
import { FetchJsonTransport } from '../shared/api/json-transport';
import { ExpoPrivateFileSystem } from '../shared/files/expo-private-file-system';
import { InProcessSnapshotOperationCoordinator } from '../shared/files/snapshot-operation-coordinator';
import { expoFetchFunction } from '../shared/infrastructure/expo-fetch-function';
import { ExpoIdGenerator } from '../shared/infrastructure/expo-id-generator';
import { SystemClock } from '../shared/lib/runtime';

export type MobileRuntime = Readonly<{
  connectServer: ConnectServer;
  serverProfiles: ServerProfileRepository;
  saveReaderProgress: SaveReaderProgress;
  loadReaderProgress: LoadReaderProgress;
}>;

function createMobileRuntime(): MobileRuntime {
  const clock = new SystemClock();
  const idGenerator = new ExpoIdGenerator();
  const fileSystem = new ExpoPrivateFileSystem();
  const snapshotOperations =
    new InProcessSnapshotOperationCoordinator();
  const transport = new FetchJsonTransport(expoFetchFunction);
  const serverProfiles = new SnapshotServerProfileRepository(
    fileSystem,
    idGenerator,
    snapshotOperations,
  );
  const readerProgressStore =
    new SnapshotReaderProgressDocumentStore(
      fileSystem,
      idGenerator,
      snapshotOperations,
    );

  return {
    connectServer: new ConnectServer(
      new ServerHealthClient(transport),
      serverProfiles,
      clock,
      idGenerator,
    ),
    serverProfiles,
    saveReaderProgress: new SaveReaderProgress(
      readerProgressStore,
      clock,
      idGenerator,
    ),
    loadReaderProgress: new LoadReaderProgress(readerProgressStore),
  };
}

export const mobileRuntime: MobileRuntime = createMobileRuntime();
