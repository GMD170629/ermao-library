import { ReaderV5IndexedDbStorage } from './v5-storage';
import { ReaderPreferenceRepository } from './preferences';
import {
  ReaderV5ProgressSyncCoordinator,
  setReaderV5ProgressSyncCoordinator
} from './v5-sync-coordinator';
import {
  readerV5ProgressQueryTransport,
  readerV5ProgressTransport
} from '../../features/reader/api/client';

export type ReaderRuntime = {
  storage: ReaderV5IndexedDbStorage;
  preferences: ReaderPreferenceRepository;
  progress: ReaderV5ProgressSyncCoordinator;
};

let runtime: ReaderRuntime | null = null;

export function getReaderRuntime(): ReaderRuntime {
  if (runtime) return runtime;
  const storage = new ReaderV5IndexedDbStorage();
  runtime = {
    storage,
    preferences: new ReaderPreferenceRepository(storage),
    progress: new ReaderV5ProgressSyncCoordinator(storage, readerV5ProgressTransport, { queryTransport: readerV5ProgressQueryTransport })
  };
  return runtime;
}

export function startReaderRuntime() {
  const current = getReaderRuntime();
  setReaderV5ProgressSyncCoordinator(current.progress);
  return current;
}

export function stopReaderRuntime() {
  setReaderV5ProgressSyncCoordinator(null);
}

export function activateReaderUser(userId: string) {
  const current = startReaderRuntime();
  current.progress.activateUser(userId);
  return current;
}

export function deactivateReaderUser() {
  runtime?.progress.deactivateUser();
}
