import { IndexedDbReaderStorage } from './storage';
import { ReaderPreferenceRepository } from './preferences';
import {
  ReaderProgressConflictError,
  type ProgressQueryTransport,
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
  const response = await fetch(`/api/reader/v4/resources/${encodeURIComponent(upload.resourceId)}/progress`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    cache: 'no-store',
    signal,
    body: JSON.stringify(upload.request)
  });
  const payload: unknown = await response.json().catch(() => null);
  const root = record(payload);
  const message = typeof record(root.error).message === 'string'
    ? String(record(root.error).message)
    : typeof root.detail === 'string' ? root.detail : undefined;
  if (response.status === 409 && record(root.error).code === 'READER_PROGRESS_CONFLICT') {
    const current = parseReaderV4ProgressSnapshot(record(root.error).current);
    if (current) throw new ReaderProgressConflictError(current);
  }
  if (!response.ok || root.ok !== true) {
    throw new Error(message ?? `阅读进度上传失败（${response.status}）`);
  }
  const data = record(root.data);
  const snapshot = parseReaderV4ProgressSnapshot(data.progress ?? data);
  if (!snapshot) throw new Error('服务端返回了无效的 Reader v4 进度快照');
  return snapshot;
};

const progressQueryTransport: ProgressQueryTransport = async (resourceId, etag, signal) => {
  const response = await fetch(`/api/reader/v4/resources/${encodeURIComponent(resourceId)}/progress`, {
    method: 'GET',
    headers: etag ? { 'If-None-Match': etag } : undefined,
    credentials: 'same-origin',
    cache: 'no-store',
    signal
  });
  const nextEtag = response.headers.get('ETag');
  if (response.status === 304) return { kind: 'unchanged', etag: nextEtag ?? etag };
  const payload: unknown = await response.json().catch(() => null);
  const root = record(payload);
  if (!response.ok || root.ok !== true) throw new Error(`阅读进度检查失败（${response.status}）`);
  const data = record(root.data);
  if (data.progressSnapshot === null) return { kind: 'current', snapshot: null, etag: nextEtag };
  const snapshot = parseReaderV4ProgressSnapshot(data.progressSnapshot);
  if (!snapshot) throw new Error('服务端返回了无效的 Reader v4 进度快照');
  return { kind: 'current', snapshot, etag: nextEtag };
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
    progress: new ReaderProgressSyncCoordinator(storage, progressTransport, { queryTransport: progressQueryTransport })
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
