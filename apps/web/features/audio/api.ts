import { withBasePath } from '../../lib/base-path';
import { clamp, orderedChapters, orderedTracks } from './audio-model';
import type { AudioBootstrap, AudioChapter, AudioLocation, AudioTrack, AudioVolumeSummary } from './types';

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
  const fileId = stringValue(item.id).trim();
  if (!fileId) return null;
  return {
    fileId,
    title: stringValue(item.title, `音轨 ${index + 1}`),
    url: withBasePath(stringValue(item.url, `/api/files/${encodeURIComponent(fileId)}`)),
    mimeType: stringValue(item.mimeType, 'audio/mpeg'),
    codec: nullableString(item.codec),
    contentHash: nullableString(item.contentHash),
    durationMs: Math.max(0, numberValue(item.durationMs)),
    discNumber: typeof item.discNumber === 'number' ? numberValue(item.discNumber) : null,
    trackNumber: typeof item.trackNumber === 'number' ? numberValue(item.trackNumber) : null,
    sortOrder: numberValue(item.sortOrder, index)
  };
}

function normalizeChapter(value: unknown, index: number): AudioChapter | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const fileId = stringValue(item.fileId).trim();
  if (!id || !fileId) return null;
  const startMs = Math.max(0, numberValue(item.startMs));
  return { id, title: stringValue(item.title, `章节 ${index + 1}`), fileId, startMs, endMs: Math.max(startMs, numberValue(item.endMs, startMs)), sortOrder: numberValue(item.index, index) };
}

function normalizeVolume(value: unknown, index: number): AudioVolumeSummary | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  if (!id) return null;
  return { id, title: stringValue(item.title, `卷 ${index + 1}`), index: numberValue(item.sortOrder, index), chapterCount: Math.max(0, numberValue(item.chapterCount)), durationMs: Math.max(0, numberValue(item.durationMs)) };
}

export function normalizeAudioBootstrap(input: unknown, requestedVolumeId = ''): AudioBootstrap {
  const root = record(input);
  const raw = root.ok === true ? record(root.data) : root;
  if (raw.schemaVersion !== 4) throw new Error('当前客户端不支持该有声书协议');
  if (raw.readerType !== 'audio') throw new Error('该卷册不是可播放的有声书');
  const book = record(raw.book);
  const mediaVersion = record(raw.mediaVersion);
  const volumeValue = record(raw.volume);
  const volume = normalizeVolume(volumeValue, 0);
  const workId = stringValue(mediaVersion.workId ?? book.id).trim();
  if (!volume || volume.id !== requestedVolumeId || !workId) throw new Error('有声书启动信息缺少卷册或作品标识');
  const tracks = orderedTracks((Array.isArray(raw.files) ? raw.files : []).map(normalizeTrack).filter((track): track is AudioTrack => track !== null));
  if (tracks.length === 0) throw new Error('这个有声书卷册还没有可播放的音频文件');
  const trackIds = new Set(tracks.map((track) => track.fileId));
  const chapters = orderedChapters((Array.isArray(raw.units) ? raw.units : []).map(normalizeChapter).filter((chapter): chapter is AudioChapter => chapter !== null && trackIds.has(chapter.fileId)));
  const calculatedDuration = tracks.reduce((sum, track) => sum + track.durationMs, 0);
  const progressSnapshot = record(raw.progressSnapshot);
  const resume = record(progressSnapshot.location);
  const resumeFileId = stringValue(resume.fileId).trim();
  const resumeLocation: AudioLocation | null = resume.kind === 'audio' && resumeFileId
    ? { type: 'audio', volumeId: volume.id, fileId: resumeFileId, chapterId: nullableString(resume.chapterId), positionMs: Math.max(0, numberValue(resume.positionMs)) }
    : null;
  const localHashes = tracks
    .flatMap((track) => track.contentHash ? [`${track.fileId}:${track.contentHash}`] : [])
    .sort();
  const serverContentFingerprint = stringValue(raw.contentFingerprint);
  return {
    schemaVersion: 4,
    userId: stringValue(raw.userId),
    readerType: 'audio',
    contentFingerprint: serverContentFingerprint,
    localContentFingerprint: localHashes.length > 0
      ? `audio-v1:${localHashes.join('|')}`
      : serverContentFingerprint,
    book: { id: stringValue(book.id, workId), title: stringValue(book.title, '未命名有声书'), author: nullableString(book.author), coverUrl: nullableString(book.coverUrl) },
    mediaVersion: { id: stringValue(mediaVersion.id), workId, mediaKind: 'AUDIOBOOK', completed: mediaVersion.completed === true },
    volume,
    availableVolumes: (Array.isArray(raw.availableVolumes) ? raw.availableVolumes : []).map(normalizeVolume).filter((item): item is AudioVolumeSummary => item !== null),
    tracks,
    chapters,
    totalDurationMs: Math.max(numberValue(volumeValue.durationMs), calculatedDuration),
    resumeLocation,
    progressPercent: clamp(numberValue(progressSnapshot.percent), 0, 100),
    serverUpdatedAtEpochMillis: typeof progressSnapshot.updatedAtEpochMillis === 'number'
      ? numberValue(progressSnapshot.updatedAtEpochMillis)
      : null,
    preferences: { playbackRate: 1, skipBackwardSeconds: 15, skipForwardSeconds: 30, volume: 1 }
  };
}

export async function fetchAudioBootstrap(volumeId: string, signal?: AbortSignal): Promise<AudioBootstrap> {
  const response = await fetch(`/api/reader/v4/volumes/${encodeURIComponent(volumeId)}/bootstrap`, { credentials: 'same-origin', cache: 'no-store', signal });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = record(payload) as ErrorPayload;
    throw new Error(error.error?.message ?? error.detail ?? `读取有声书启动信息失败（${response.status}）`);
  }
  return normalizeAudioBootstrap(payload, volumeId);
}
