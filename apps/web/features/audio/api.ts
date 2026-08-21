import { parsePublicationLocation } from '@shuku/reader-core';
import { withBasePath } from '../../lib/base-path';
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

function normalizeTrack(value: unknown, index: number): AudioTrack | null {
  const item = record(value);
  const assetId = stringValue(item.id ?? item.assetId).trim();
  if (!assetId) return null;
  return {
    assetId,
    title: stringValue(item.title, `音轨 ${index + 1}`),
    url: withBasePath(stringValue(item.url, `/api/assets/${encodeURIComponent(assetId)}`)),
    mimeType: stringValue(item.mimeType, 'audio/mpeg'),
    codec: nullableString(item.codec),
    durationMs: Math.max(0, numberValue(item.durationMs)),
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
  const startMs = Math.max(0, numberValue(item.startMs));
  return {
    id,
    title: stringValue(item.title, `章节 ${index + 1}`),
    assetId,
    startMs,
    endMs: Math.max(startMs, numberValue(item.endMs, startMs)),
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
    durationMs: Math.max(0, numberValue(item.durationMs))
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
  if (tracks.length === 0) throw new Error('这个有声资源还没有可播放的音频资产');
  const trackIds = new Set(tracks.map((track) => track.assetId));
  const chapters = orderedChapters(
    (Array.isArray(raw.units) ? raw.units : [])
      .map(normalizeChapter)
      .filter((chapter): chapter is AudioChapter => chapter !== null && trackIds.has(chapter.assetId))
  );
  const calculatedDuration = tracks.reduce((sum, track) => sum + track.durationMs, 0);
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
    resourceCompleted: raw.resourceCompleted === true,
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
    signal
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = record(payload) as ErrorPayload;
    throw new Error(error.error?.message ?? error.detail ?? `读取有声书启动信息失败（${response.status}）`);
  }
  return normalizeAudioBootstrap(payload, resourceId);
}
