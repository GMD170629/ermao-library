import { apiV2Fetch } from '@/lib/api-v2';
import { IndexedDbReaderV2Storage } from './storage';
import { ReaderPreferenceRepository } from './preferences';
import {
  toProgressPutBody,
  type ProgressMutation,
  type ProgressSyncResult,
  type ReaderProgressLocation
} from './model';
import { ReaderProgressSyncCoordinator, setReaderProgressSyncCoordinator } from './sync-coordinator';

export function toWireLocation(location: ReaderProgressLocation) {
  if (location.kind === 'audio') {
    return {
      type: 'audio' as const,
      volumeId: location.volumeId,
      fileId: location.fileId,
      chapterId: location.chapterId,
      positionMs: location.positionMs
    };
  }
  if (location.kind === 'epub') {
    return {
      type: 'epub' as const,
      cfi: location.cfi,
      href: location.href,
      spineIndex: location.spineIndex,
      progression: location.progression
    };
  }
  if (location.kind === 'comic') {
    return { type: 'comic' as const, volumeId: location.volumeId, pageIndex: location.pageIndex };
  }
  return { type: 'pdf' as const, pageNumber: location.pageNumber };
}

async function progressTransport(mutation: Readonly<ProgressMutation>, signal: AbortSignal): Promise<ProgressSyncResult> {
  const body = toProgressPutBody(mutation);
  const response = await apiV2Fetch(`/api/v2/reading/editions/${encodeURIComponent(mutation.editionId)}/progress`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    cache: 'no-store',
    signal,
    body: JSON.stringify({
      deviceId: body.clientId,
      position: {
        schemaVersion: body.schemaVersion,
        mutationId: body.mutationId,
        clientSequence: body.clientSequence,
        contentFingerprint: body.contentFingerprint,
        volumeId: body.volumeId,
        location: toWireLocation(body.location)
      },
      percentage: Math.max(0, Math.min(1, body.percent / 100)),
      occurredAt: new Date(mutation.updatedAt).toISOString()
    })
  });
  const payload = await response.json().catch(() => null) as {
    detail?: string;
  } | null;
  if (response.ok) return { outcome: 'accepted' };

  const message = payload?.detail;
  if (response.status === 409) return { outcome: 'stale' };
  // Authentication expiry is recoverable: keep the durable mutation so a
  // subsequent login can resume it. A 403 is an actual user/ownership mismatch.
  if (response.status === 401) throw new Error(message ?? '登录已过期，阅读进度将在重新登录后同步');
  if ([400, 403, 404, 410, 422].includes(response.status)) {
    return { outcome: 'terminal', message: message ?? `进度协议被拒绝（${response.status}）` };
  }
  throw new Error(message ?? `进度同步失败（${response.status}）`);
}

export type ReaderV2Runtime = {
  storage: IndexedDbReaderV2Storage;
  preferences: ReaderPreferenceRepository;
  progress: ReaderProgressSyncCoordinator;
};

let runtime: ReaderV2Runtime | null = null;

export function getReaderV2Runtime(): ReaderV2Runtime {
  if (runtime) return runtime;
  const storage = new IndexedDbReaderV2Storage();
  runtime = {
    storage,
    preferences: new ReaderPreferenceRepository(storage),
    progress: new ReaderProgressSyncCoordinator(storage, progressTransport)
  };
  return runtime;
}

export function startReaderV2Runtime() {
  const current = getReaderV2Runtime();
  setReaderProgressSyncCoordinator(current.progress);
  return current;
}

export function stopReaderV2Runtime() {
  setReaderProgressSyncCoordinator(null);
}

export function activateReaderV2User(userId: string) {
  const current = startReaderV2Runtime();
  current.progress.activateUser(userId);
  return current;
}

export function deactivateReaderV2User() {
  runtime?.progress.deactivateUser();
}
