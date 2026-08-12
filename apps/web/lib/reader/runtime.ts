import { IndexedDbReaderStorage } from './storage';
import { ReaderPreferenceRepository } from './preferences';
import {
  type ProgressSyncTransport
} from './model';
import { parseReaderV4ProgressSnapshot } from './progress-wire';
import { ReaderProgressSyncCoordinator, setReaderProgressSyncCoordinator } from './sync-coordinator';

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

const progressTransport: ProgressSyncTransport = async (upload, signal) => {
  const response = await fetch(`/api/reader/v4/volumes/${encodeURIComponent(upload.volumeId)}/progress`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    cache: 'no-store',
    signal,
    body: JSON.stringify(upload.snapshot)
  });
  const payload: unknown = await response.json().catch(() => null);
  const root = record(payload);
  const message = typeof record(root.error).message === 'string'
    ? String(record(root.error).message)
    : typeof root.detail === 'string' ? root.detail : undefined;
  if (!response.ok || root.ok !== true) {
    throw new Error(message ?? `阅读进度上传失败（${response.status}）`);
  }
  const snapshot = parseReaderV4ProgressSnapshot(record(root.data).progress);
  if (!snapshot) throw new Error('服务端返回了无效的 Reader v4 进度快照');
  return snapshot;
};

export type ReaderRuntime = {
  storage: IndexedDbReaderStorage;
  preferences: ReaderPreferenceRepository;
  progress: ReaderProgressSyncCoordinator;
};

let runtime: ReaderRuntime | null = null;

export function getReaderRuntime(): ReaderRuntime {
  if (runtime) return runtime;
  const storage = new IndexedDbReaderStorage();
  runtime = {
    storage,
    preferences: new ReaderPreferenceRepository(storage),
    progress: new ReaderProgressSyncCoordinator(storage, progressTransport)
  };
  return runtime;
}

export function startReaderRuntime() {
  const current = getReaderRuntime();
  setReaderProgressSyncCoordinator(current.progress);
  return current;
}

export function stopReaderRuntime() {
  setReaderProgressSyncCoordinator(null);
}

export function activateReaderUser(userId: string) {
  const current = startReaderRuntime();
  current.progress.activateUser(userId);
  return current;
}

export function deactivateReaderUser() {
  runtime?.progress.deactivateUser();
}
