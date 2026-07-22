import { withBasePath } from '../../lib/base-path';
import { clamp, orderedChapters, orderedTracks } from './audio-model';
import type { AudioBootstrap, AudioChapter, AudioLocation, AudioTrack } from './types';

type ErrorPayload = { error?: { message?: string }; detail?: string };

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = '') {
  return typeof value === 'string' ? value : fallback;
}

function nullableString(value: unknown) {
  return typeof value === 'string' && value.trim() ? value : null;
}

function numberValue(value: unknown, fallback = 0) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function normalizeTrack(value: unknown, index: number): AudioTrack | null {
  const item = record(value);
  const fileId = stringValue(item.fileId ?? item.file_id).trim();
  if (!fileId) return null;
  const url = stringValue(item.url, `/api/files/${encodeURIComponent(fileId)}`);
  return {
    fileId,
    title: stringValue(item.title, `音轨 ${index + 1}`),
    url: withBasePath(url),
    mimeType: stringValue(item.mimeType ?? item.mime_type, 'audio/mpeg'),
    durationMs: Math.max(0, numberValue(item.durationMs ?? item.duration_ms)),
    discNumber: typeof (item.discNumber ?? item.disc_number) === 'number' ? numberValue(item.discNumber ?? item.disc_number) : null,
    trackNumber: typeof (item.trackNumber ?? item.track_number) === 'number' ? numberValue(item.trackNumber ?? item.track_number) : null,
    sortOrder: numberValue(item.sortOrder ?? item.sort_order, index)
  };
}

function normalizeChapter(value: unknown, index: number): AudioChapter | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const fileId = stringValue(item.fileId ?? item.file_id).trim();
  if (!id || !fileId) return null;
  const startMs = Math.max(0, numberValue(item.startMs ?? item.start_ms));
  return {
    id,
    title: stringValue(item.title, `章节 ${index + 1}`),
    fileId,
    startMs,
    endMs: Math.max(startMs, numberValue(item.endMs ?? item.end_ms, startMs)),
    sortOrder: numberValue(item.sortOrder ?? item.sort_order, index)
  };
}

function normalizeLocation(value: unknown): AudioLocation | null {
  const item = record(value);
  if ((item.type ?? item.kind) !== 'audio') return null;
  const fileId = stringValue(item.fileId ?? item.file_id).trim();
  if (!fileId) return null;
  return {
    type: 'audio',
    volumeId: nullableString(item.volumeId ?? item.volume_id),
    fileId,
    chapterId: nullableString(item.chapterId ?? item.chapter_id),
    positionMs: Math.max(0, numberValue(item.positionMs ?? item.position_ms))
  };
}

export function normalizeAudioBootstrap(input: unknown, requestedEditionId = ''): AudioBootstrap {
  const root = record(input);
  const raw = root.ok === true && root.data ? record(root.data) : root;
  const schemaVersion = raw.schemaVersion ?? raw.schema_version;
  if (schemaVersion !== undefined && schemaVersion !== 2) throw new Error('当前客户端不支持这个有声书启动协议版本');
  if (raw.readerType !== 'audio' && raw.reader_type !== 'audio') throw new Error('该版本不是可播放的有声书');

  const book = record(raw.book ?? raw.work);
  const edition = record(raw.edition);
  const serverPreferences = record(raw.serverPreferences ?? raw.server_preferences);
  const preferenceSettings = record(serverPreferences.settings);
  const audioPreferences = record(preferenceSettings.audio);
  const tracks = orderedTracks((Array.isArray(raw.tracks) ? raw.tracks : []).map(normalizeTrack).filter((track): track is AudioTrack => Boolean(track)));
  if (tracks.length === 0) throw new Error('这个有声书版本还没有可播放的音频文件');
  const trackIds = new Set(tracks.map((track) => track.fileId));
  const chapters = orderedChapters((Array.isArray(raw.chapters) ? raw.chapters : []).map(normalizeChapter).filter((chapter): chapter is AudioChapter => chapter !== null && trackIds.has(chapter.fileId)));
  const calculatedDuration = tracks.reduce((sum, track) => sum + track.durationMs, 0);
  const resumeLocation = normalizeLocation(raw.resumeLocation ?? raw.resume_location);
  const selectedVolume = record(raw.selectedVolume ?? raw.selected_volume);
  const editionId = stringValue(edition.id, requestedEditionId);
  const workId = stringValue(edition.workId ?? edition.work_id ?? book.id);
  if (!editionId || !workId) throw new Error('有声书启动信息缺少版本或图书标识');

  return {
    schemaVersion: 2,
    userId: stringValue(raw.userId ?? raw.user_id),
    readerType: 'audio',
    contentFingerprint: stringValue(raw.contentFingerprint ?? raw.content_fingerprint),
    book: {
      id: stringValue(book.id, workId),
      title: stringValue(book.title, '未命名有声书'),
      author: nullableString(book.author),
      coverUrl: nullableString(book.coverUrl ?? book.cover_url)
    },
    edition: {
      id: editionId,
      workId,
      versionName: stringValue(edition.versionName ?? edition.version_name, '有声书'),
      narrator: nullableString(edition.narrator ?? raw.narrator)
    },
    tracks,
    chapters,
    totalDurationMs: Math.max(numberValue(raw.totalDurationMs ?? raw.total_duration_ms), calculatedDuration),
    volumeId: nullableString(selectedVolume.id) ?? resumeLocation?.volumeId ?? null,
    resumeLocation,
    progressPercent: clamp(numberValue(raw.progressPercent ?? raw.progress_percent), 0, 100),
    preferences: {
      playbackRate: clamp(numberValue(audioPreferences.playbackRate ?? audioPreferences.playback_rate, 1), 0.75, 3),
      skipBackwardSeconds: Math.round(clamp(numberValue(audioPreferences.skipBackwardSeconds ?? audioPreferences.skip_backward_seconds, 15), 5, 120)),
      skipForwardSeconds: Math.round(clamp(numberValue(audioPreferences.skipForwardSeconds ?? audioPreferences.skip_forward_seconds, 30), 5, 120)),
      volume: clamp(numberValue(audioPreferences.volume, 1), 0, 1)
    }
  };
}

export async function fetchAudioBootstrap(editionId: string, signal?: AbortSignal) {
  const response = await fetch(`/api/reader/v2/editions/${encodeURIComponent(editionId)}/bootstrap`, {
    credentials: 'same-origin',
    cache: 'no-store',
    signal
  });
  const payload = await response.json().catch(() => null) as unknown;
  if (!response.ok) {
    const error = record(payload) as ErrorPayload;
    throw new Error(error.error?.message ?? error.detail ?? `读取有声书启动信息失败（${response.status}）`);
  }
  return normalizeAudioBootstrap(payload, editionId);
}
