import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_PROFILES,
  READER_SAFETY_RULE_IDS,
  parsePublicationLocation
} from '@shuku/reader-core';
import { withBasePath } from '../../lib/base-path';
import { readBoundedResponse, ResponseLimitError } from '../../shared/api/bounded-response';
import { rejectReaderSafety } from '../reader/v3/security/reader-safety-policy';
import { clamp, orderedChapters, orderedTracks } from './audio-model';
import type { AudioBootstrap, AudioChapter, AudioLocation, AudioResourceSummary, AudioTrack } from './types';

type ErrorPayload = Readonly<{ error?: Readonly<{ message?: string }>; detail?: string }>;

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function safeNonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

const AUDIO_MIME_TYPES = new Set<string>(Object.values(READER_SAFETY_PROFILES.audio.containerMimeTypes));

function audioAssetUrl(value: unknown, assetId: string): string {
  const raw = stringValue(value, `/api/assets/${encodeURIComponent(assetId)}`).trim();
  if (!raw.startsWith('/') || raw.startsWith('//') || !raw.split('?', 1)[0]?.includes('/api/')) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.AUDIO_REDIRECT_POLICY);
  }
  return withBasePath(raw);
}

function normalizeTrack(value: unknown, index: number): AudioTrack | null {
  const item = record(value);
  const assetId = stringValue(item.id ?? item.assetId).trim();
  if (!assetId) return null;
  const mimeType = stringValue(item.mimeType).split(';', 1)[0]?.trim().toLowerCase() ?? '';
  if (!AUDIO_MIME_TYPES.has(mimeType)) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.AUDIO_CONTAINER_MIME);
  }
  const durationMs = safeNonNegativeInteger(item.durationMs);
  if (durationMs === null) rejectReaderSafety(READER_SAFETY_RULE_IDS.AUDIO_TRACK_AND_CHAPTER_BOUNDS);
  const sizeBytes = item.sizeBytes === undefined ? null : safeNonNegativeInteger(item.sizeBytes);
  if (item.sizeBytes !== undefined && (sizeBytes === null || sizeBytes > READER_SAFETY_BUDGETS.originalMaxBytes)) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.AUDIO_ORIGINAL_MAX_BYTES);
  }
  return {
    assetId,
    title: stringValue(item.title, `音轨 ${index + 1}`),
    url: audioAssetUrl(item.url, assetId),
    mimeType,
    codec: nullableString(item.codec),
    durationMs,
    discNumber: typeof item.discNumber === 'number' ? numberValue(item.discNumber) : null,
    trackNumber: typeof item.trackNumber === 'number' ? numberValue(item.trackNumber) : null,
    sortOrder: numberValue(item.sortOrder, index)
  };
}

function normalizeChapter(value: unknown, index: number): AudioChapter | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const assetId = stringValue(item.assetId).trim();
  if (!id || !assetId) return null;
  const startMs = safeNonNegativeInteger(item.startMs);
  const endMs = safeNonNegativeInteger(item.endMs);
  if (startMs === null || endMs === null || endMs < startMs) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.AUDIO_TRACK_AND_CHAPTER_BOUNDS);
  }
  return {
    id,
    title: stringValue(item.title, `章节 ${index + 1}`),
    assetId,
    startMs,
    endMs,
    sortOrder: numberValue(item.sortOrder ?? item.index, index)
  };
}

function normalizeResource(value: unknown, index: number, bookId: string): AudioResourceSummary | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const resourceBookId = stringValue(item.bookId, bookId).trim();
  if (!id || !resourceBookId) return null;
  return {
    id,
    bookId: resourceBookId,
    title: stringValue(item.title, `资源 ${index + 1}`),
    sortOrder: numberValue(item.sortOrder ?? item.resourceIndex, index),
    chapterCount: Math.max(0, numberValue(item.chapterCount)),
    durationMs: Math.max(0, numberValue(item.durationMs)),
    resourceCompleted: item.resourceCompleted === true
  };
}

export function normalizeAudioBootstrap(input: unknown, requestedResourceId = ''): AudioBootstrap {
  const root = record(input);
  const raw = root.ok === true ? record(root.data) : root;
  if (raw.schemaVersion !== 4) throw new Error('当前客户端不支持该有声书协议');
  if (raw.readerType !== 'audio') throw new Error('该资源不是可播放的有声书');
  const book = record(raw.book);
  const bookId = stringValue(book.id).trim();
  const resource = normalizeResource(raw.resource, 0, bookId);
  if (!bookId || !resource || (requestedResourceId && resource.id !== requestedResourceId)) {
    throw new Error('有声书启动信息缺少资源或图书标识');
  }
  const tracks = orderedTracks(
    (Array.isArray(raw.assets) ? raw.assets : [])
      .map(normalizeTrack)
      .filter((track): track is AudioTrack => track !== null)
  );
  if (tracks.length > READER_SAFETY_BUDGETS.audioTrackMaxCount
    || new Set(tracks.map((track) => track.assetId)).size !== tracks.length) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.AUDIO_TRACK_AND_CHAPTER_BOUNDS);
  }
  if (tracks.length === 0) throw new Error('这个有声资源还没有可播放的音频资产');
  const trackIds = new Set(tracks.map((track) => track.assetId));
  const chapters = orderedChapters(
    (Array.isArray(raw.units) ? raw.units : [])
      .map(normalizeChapter)
      .filter((chapter): chapter is AudioChapter => chapter !== null && trackIds.has(chapter.assetId))
  );
  if (chapters.length > READER_SAFETY_BUDGETS.audioChapterMaxCount
    || new Set(chapters.map((chapter) => chapter.id)).size !== chapters.length
    || chapters.some((chapter) => {
      const track = tracks.find((candidate) => candidate.assetId === chapter.assetId);
      return !track || chapter.endMs > track.durationMs;
    })) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.AUDIO_TRACK_AND_CHAPTER_BOUNDS);
  }
  const calculatedDuration = tracks.reduce((sum, track) => {
    const total = sum + track.durationMs;
    if (!Number.isSafeInteger(total)) rejectReaderSafety(READER_SAFETY_RULE_IDS.AUDIO_TRACK_AND_CHAPTER_BOUNDS);
    return total;
  }, 0);
  const progressSnapshot = record(raw.progressSnapshot);
  const resume = parsePublicationLocation(progressSnapshot.locator);
  if (raw.progressSnapshot !== null && raw.progressSnapshot !== undefined && !resume) {
    throw new Error('阅读器启动信息包含无效的 Reader v4 进度快照');
  }
  const resumeLocation: AudioLocation | null = resume?.kind === 'audio'
    ? { type: 'audio', resourceId: resource.id, assetId: resume.assetId, chapterId: resume.chapterId ?? null, positionMs: resume.positionMillis }
    : null;
  const availableResources = (Array.isArray(raw.availableResources) ? raw.availableResources : [])
    .map((item, index) => normalizeResource(item, index, bookId))
    .filter((item): item is AudioResourceSummary => item !== null);
  return {
    schemaVersion: 4,
    userId: stringValue(raw.userId),
    readerType: 'audio',
    progressRevision: Math.max(0, numberValue(progressSnapshot.revision)),
    book: {
      id: bookId,
      title: stringValue(book.title, '未命名有声书'),
      author: nullableString(book.author),
      coverUrl: nullableString(book.coverUrl)
    },
    resource,
    resourceCompleted: resource.resourceCompleted,
    availableResources,
    tracks,
    chapters,
    totalDurationMs: Math.max(resource.durationMs, calculatedDuration),
    resumeLocation,
    progressPercent: clamp(numberValue(progressSnapshot.displayPercent), 0, 100),
    serverUpdatedAtEpochMillis: typeof progressSnapshot.receivedAtEpochMillis === 'number'
      ? numberValue(progressSnapshot.receivedAtEpochMillis)
      : null,
    preferences: { playbackRate: 1, skipBackwardSeconds: 15, skipForwardSeconds: 30, volume: 1 }
  };
}

export async function fetchAudioBootstrap(resourceId: string, signal?: AbortSignal): Promise<AudioBootstrap> {
  const response = await fetch(`/api/reader/v4/resources/${encodeURIComponent(resourceId)}/bootstrap`, {
    credentials: 'same-origin',
    cache: 'no-store',
    redirect: 'error',
    signal
  });
  let bytes: Uint8Array<ArrayBuffer>;
  try {
    bytes = await readBoundedResponse(response, READER_SAFETY_BUDGETS.audioMetadataMaxBytes);
  } catch (reason) {
    if (reason instanceof ResponseLimitError && reason.code === 'RESPONSE_TOO_LARGE') {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.AUDIO_METADATA_BUDGET, { cause: reason });
    }
    throw reason;
  }
  const payload: unknown = (() => {
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
    catch { return null; }
  })();
  if (!response.ok) {
    const error = record(payload) as ErrorPayload;
    throw new Error(error.error?.message ?? error.detail ?? `读取有声书启动信息失败（${response.status}）`);
  }
  return normalizeAudioBootstrap(payload, resourceId);
}
