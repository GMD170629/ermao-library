import {
  normalizeReaderPreferences,
  type ReaderKind,
  type ReaderLocation
} from '@shuku/reader-core';
import { emitReaderDebug } from './debug';
import type { ProgressMutationInput } from './model';
import type { ReaderPreferenceRepository } from './preferences';
import type { ReaderProgressSyncCoordinator } from './sync-coordinator';
import type { ReaderV2Storage } from './storage';

type LegacyPreferenceCandidate = {
  userId?: string;
  workId?: string;
  settings: unknown;
  sourceKey?: string;
};

type LegacyProgressCandidate = {
  userId?: string;
  workId?: string;
  editionId?: string;
  contentFingerprint?: string;
  volumeId?: string | null;
  readerType?: ReaderKind | 'epub' | 'ebook' | 'unknown';
  progress: unknown;
  sourceKey?: string;
};

export type LegacyMigrationResult = { status: 'migrated' | 'skipped' | 'quarantined'; reason?: string };
type ProgressEnqueuer = Pick<ReaderProgressSyncCoordinator, 'enqueue'>;

function record(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try {
      return record(JSON.parse(value));
    } catch {
      return {};
    }
  }
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function finite(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function nonEmpty(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

async function quarantineUnsafeLegacy(storage: ReaderV2Storage, source: string, reason: string) {
  await storage.addDiagnostic({
    level: 'warning',
    code: 'unsafe-legacy',
    message: `旧阅读数据未迁移：${reason}`,
    data: { source }
  });
  emitReaderDebug('warning', '旧阅读数据因身份不明确而隔离', { source, reason });
  return { status: 'quarantined', reason } satisfies LegacyMigrationResult;
}

export async function migrateLegacyPreferenceCandidate(
  candidate: LegacyPreferenceCandidate,
  repository: ReaderPreferenceRepository,
  storage: ReaderV2Storage
): Promise<LegacyMigrationResult> {
  if (!nonEmpty(candidate.userId) || !nonEmpty(candidate.workId)) {
    return quarantineUnsafeLegacy(storage, candidate.sourceKey ?? 'legacy-preference', '缺少可靠的用户或作品标识');
  }
  if (await storage.getPreference(candidate.userId, candidate.workId)) return { status: 'skipped', reason: '本地 V2 快照已存在' };
  await repository.save(candidate.userId, candidate.workId, normalizeReaderPreferences(candidate.settings));
  emitReaderDebug('info', '旧阅读偏好已迁移为本书完整快照', { workId: candidate.workId, source: candidate.sourceKey });
  return { status: 'migrated' };
}

function legacyLocation(candidate: LegacyProgressCandidate, progress: Record<string, unknown>): ReaderLocation | null {
  const extra = record(progress.extra);
  const rawKind = candidate.readerType ?? progress.readerType;
  const kind = rawKind === 'ebook' || rawKind === 'reflowable' ? 'epub' : rawKind;
  if (kind === 'epub') {
    const cfi = nonEmpty(extra.cfi) ? extra.cfi : nonEmpty(progress.position) && progress.position.startsWith('epubcfi(') ? progress.position : undefined;
    const href = nonEmpty(extra.currentHref) ? extra.currentHref : nonEmpty(extra.chapterHref) ? extra.chapterHref : undefined;
    const rawProgression = finite(extra.progression) ?? finite(extra.percentage);
    const progression = rawProgression === undefined
      ? undefined
      : Math.max(0, Math.min(1, rawProgression > 1 ? rawProgression / 100 : rawProgression));
    if (!cfi && !href && progression === undefined) return null;
    return { kind: 'reflowable', format: 'epub', cfi, href, progression };
  }
  if (kind === 'comic') {
    const pageIndex = finite(progress.page) ?? finite(extra.pageIndex);
    const volumeId = nonEmpty(candidate.volumeId)
      ? candidate.volumeId
      : nonEmpty(extra.volumeId) ? extra.volumeId : null;
    if (pageIndex === undefined || !volumeId) return null;
    return { kind: 'comic', volumeId, pageIndex: Math.max(1, Math.round(pageIndex)) };
  }
  if (kind === 'pdf') {
    const pageNumber = finite(progress.page) ?? finite(extra.pageIndex) ?? (nonEmpty(progress.position) ? Number(progress.position) : undefined);
    if (pageNumber === undefined || !Number.isFinite(pageNumber)) return null;
    return { kind: 'pdf', pageNumber: Math.max(1, Math.round(pageNumber)) };
  }
  return null;
}

export async function migrateLegacyProgressCandidate(
  candidate: LegacyProgressCandidate,
  coordinator: ProgressEnqueuer,
  storage: ReaderV2Storage
): Promise<LegacyMigrationResult> {
  if (!nonEmpty(candidate.userId) || !nonEmpty(candidate.workId) || !nonEmpty(candidate.editionId) || !nonEmpty(candidate.contentFingerprint)) {
    return quarantineUnsafeLegacy(storage, candidate.sourceKey ?? 'legacy-progress', '缺少可靠的用户、作品、版本或内容指纹');
  }
  const progress = record(candidate.progress);
  const location = legacyLocation(candidate, progress);
  if (!location) return quarantineUnsafeLegacy(storage, candidate.sourceKey ?? 'legacy-progress', '无法确定阅读格式或位置');
  const extra = record(progress.extra);
  const percent = finite(progress.percent) ?? finite(extra.percentage) ?? 0;
  const input: ProgressMutationInput = {
    userId: candidate.userId,
    workId: candidate.workId,
    editionId: candidate.editionId,
    volumeId: location.kind === 'comic'
      ? location.volumeId
      : candidate.volumeId ?? (nonEmpty(extra.volumeId) ? extra.volumeId : null),
    contentFingerprint: candidate.contentFingerprint,
    location,
    percent
  };
  await coordinator.enqueue(input);
  emitReaderDebug('info', '旧阅读进度已迁移到 V2 顺序队列', { editionId: candidate.editionId, source: candidate.sourceKey });
  return { status: 'migrated' };
}
