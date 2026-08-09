import {
  LoadReaderProgress,
  SaveReaderProgress,
  SnapshotReaderProgressDocumentStore,
} from '../features/reader-progress/public';
import {
  CookieSessionClient,
  IdentitySession,
} from '../features/identity/public';
import {
  ConnectServer,
  DeleteServerProfile,
  LoadServerProfiles,
  ResetCorruptServerProfiles,
  SelectServerProfile,
  ServerHealthClient,
  SnapshotServerProfileRepository,
} from '../features/server-connection/public';
import {
  FetchApiTransport,
  type ApiTransport,
} from '../shared/api/public';
import { ExpoPrivateFileSystem } from '../shared/files/expo-private-file-system';
import { InProcessSnapshotOperationCoordinator } from '../shared/files/snapshot-operation-coordinator';
import { expoFetchFunction } from '../shared/infrastructure/expo-fetch-function';
import { ExpoIdGenerator } from '../shared/infrastructure/expo-id-generator';
import { SystemClock } from '../shared/lib/runtime';

export type MobileRuntime = Readonly<{
  apiTransport: ApiTransport;
  connectServer: ConnectServer;
  deleteServerProfile: DeleteServerProfile;
  identitySession: IdentitySession;
  loadServerProfiles: LoadServerProfiles;
  resetCorruptServerProfiles: ResetCorruptServerProfiles;
  selectServerProfile: SelectServerProfile;
  saveReaderProgress: SaveReaderProgress;
  loadReaderProgress: LoadReaderProgress;
}>;

function createMobileRuntime(): MobileRuntime {
  const clock = new SystemClock();
  const idGenerator = new ExpoIdGenerator();
  const fileSystem = new ExpoPrivateFileSystem();
  const snapshotOperations =
    new InProcessSnapshotOperationCoordinator();
  const transport = new FetchApiTransport(expoFetchFunction);
  const serverHealth = new ServerHealthClient(transport);
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
    apiTransport: transport,
    connectServer: new ConnectServer(
      serverHealth,
      serverProfiles,
      clock,
      idGenerator,
    ),
    deleteServerProfile: new DeleteServerProfile(serverProfiles, clock),
    identitySession: new IdentitySession(new CookieSessionClient(transport)),
    loadServerProfiles: new LoadServerProfiles(serverProfiles),
    resetCorruptServerProfiles: new ResetCorruptServerProfiles(
      serverProfiles,
    ),
    selectServerProfile: new SelectServerProfile(
      serverHealth,
      serverProfiles,
      clock,
    ),
    saveReaderProgress: new SaveReaderProgress(
      readerProgressStore,
      clock,
      idGenerator,
    ),
    loadReaderProgress: new LoadReaderProgress(readerProgressStore),
  };
}

export const mobileRuntime: MobileRuntime = createMobileRuntime();
