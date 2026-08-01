import type { MediaKind, MediaVersionResource, VolumeFormat, VolumeResource, WorkView } from '../../../types/work';

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function mediaKind(value: unknown): MediaKind | null {
  return value === 'EBOOK' || value === 'COMIC' || value === 'AUDIOBOOK' ? value : null;
}

function volumeFormat(value: unknown): VolumeFormat | null {
  return value === 'COMIC' || value === 'EPUB' || value === 'PDF' || value === 'AUDIO' || value === 'MOBI' || value === 'AZW' || value === 'AZW3' || value === 'PRC' || value === 'FB2' || value === 'TXT' ? value : null;
}

function mapVolume(value: unknown): VolumeResource | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const mediaVersionId = stringValue(item.mediaVersionId).trim();
  const format = volumeFormat(item.format);
  if (!id || !mediaVersionId || !format) return null;
  const files = (Array.isArray(item.files) ? item.files : []).flatMap((rawFile) => {
    const file = record(rawFile);
    const fileId = stringValue(file.id).trim();
    if (!fileId) return [];
    return [{
      id: fileId,
      volumeId: id,
      path: stringValue(file.path),
      mimeType: stringValue(file.mimeType),
      kind: stringValue(file.kind),
      sortOrder: finiteNumber(file.sortOrder),
      sizeBytes: finiteNumber(file.sizeBytes),
      size: stringValue(file.size),
      durationMs: nullableNumber(file.durationMs),
      codec: nullableString(file.codec),
      bitrate: nullableNumber(file.bitrate),
      sampleRate: nullableNumber(file.sampleRate),
      channels: nullableNumber(file.channels),
      discNumber: nullableNumber(file.discNumber),
      trackNumber: nullableNumber(file.trackNumber),
      url: nullableString(file.url) ?? undefined
    }];
  });
  return {
    id,
    mediaVersionId,
    title: stringValue(item.title, id),
    volumeIndex: nullableNumber(item.volumeIndex),
    sortOrder: finiteNumber(item.sortOrder),
    format,
    derivedFromVolumeId: nullableString(item.derivedFromVolumeId),
    publisher: nullableString(item.publisher),
    publishedAt: nullableString(item.publishedAt),
    language: nullableString(item.language),
    isbn: nullableString(item.isbn),
    identifier: nullableString(item.identifier),
    narrator: nullableString(item.narrator),
    abridged: typeof item.abridged === 'boolean' ? item.abridged : null,
    importStatus: stringValue(item.importStatus),
    importError: nullableString(item.importError),
    coverUrl: stringValue(item.coverUrl),
    pageCount: nullableNumber(item.pageCount),
    chapterCount: nullableNumber(item.chapterCount),
    durationMs: nullableNumber(item.durationMs),
    trackCount: nullableNumber(item.trackCount),
    progress: Math.max(0, Math.min(100, finiteNumber(item.progress))),
    lastReadAt: nullableString(item.lastReadAt),
    hidden: item.hidden === true,
    readable: item.readable !== false,
    conversionAvailable: item.conversionAvailable === true,
    files
  };
}

function mapMediaVersion(value: unknown): MediaVersionResource | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const kind = mediaKind(item.mediaKind);
  if (!id || !kind) return null;
  return {
    id,
    mediaKind: kind,
    completed: item.completed === true,
    volumes: (Array.isArray(item.volumes) ? item.volumes : []).map(mapVolume).filter((volume): volume is VolumeResource => volume !== null)
  };
}

export function mapWorkView(value: unknown): WorkView {
  const root = record(value);
  const id = stringValue(root.id).trim();
  if (!id || !Array.isArray(root.mediaVersions)) throw new Error('作品响应缺少媒介版本结构');
  const recentMediaKind = mediaKind(root.recentMediaKind);
  const publicationStatus = root.publicationStatus === 'ONGOING' || root.publicationStatus === 'COMPLETED' || root.publicationStatus === 'HIATUS' || root.publicationStatus === 'CANCELLED' ? root.publicationStatus : 'UNKNOWN';
  const trackingStatus = root.trackingStatus === 'TRACKING' || root.trackingStatus === 'PAUSED' || root.trackingStatus === 'IGNORED' ? root.trackingStatus : 'NOT_TRACKING';
  return {
    id,
    title: stringValue(root.title, '未命名作品'),
    author: stringValue(root.author, '未知作者'),
    description: stringValue(root.description),
    seriesName: nullableString(root.seriesName),
    seriesIndex: nullableNumber(root.seriesIndex),
    tags: Array.isArray(root.tags) ? root.tags.filter((tag): tag is string => typeof tag === 'string') : [],
    publicationStatus,
    trackingStatus,
    ignored: root.ignored === true,
    organized: root.organized === true,
    metadataQuality: finiteNumber(root.metadataQuality),
    addedAt: stringValue(root.addedAt),
    updatedAt: stringValue(root.updatedAt),
    coverUrl: stringValue(root.coverUrl),
    coverStatus: stringValue(root.coverStatus),
    gradient: stringValue(root.gradient),
    recentMediaKind,
    continueVolumeId: nullableString(root.continueVolumeId),
    completed: root.completed === true,
    mediaVersions: root.mediaVersions.map(mapMediaVersion).filter((item): item is MediaVersionResource => item !== null)
  };
}

async function apiJson(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...init });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = record(payload);
    const nestedError = record(error.error);
    throw new Error(stringValue(nestedError.message) || stringValue(error.detail) || `请求失败（${response.status}）`);
  }
  const envelope = record(payload);
  return envelope.ok === true && 'data' in envelope ? envelope.data : payload;
}

export async function fetchWork(workId: string, signal?: AbortSignal): Promise<WorkView> {
  const data = record(await apiJson(`/api/works/${encodeURIComponent(workId)}`, { signal }));
  return mapWorkView(data.book ?? data.work ?? data);
}

export async function updateVolume(workId: string, volumeId: string, body: Record<string, unknown>): Promise<void> {
  await apiJson(`/api/works/${encodeURIComponent(workId)}/volumes/${encodeURIComponent(volumeId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export async function runVolumeAction(workId: string, volumeId: string, action: 'convert' | 'split' | 'move' | 'move-to', body?: Record<string, unknown>): Promise<void> {
  await apiJson(`/api/works/${encodeURIComponent(workId)}/volumes/${encodeURIComponent(volumeId)}/${action}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
}

export async function deleteVolume(workId: string, volumeId: string): Promise<void> {
  await apiJson(`/api/works/${encodeURIComponent(workId)}/volumes/${encodeURIComponent(volumeId)}`, { method: 'DELETE' });
}
