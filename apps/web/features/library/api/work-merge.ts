import type { MediaKind } from '../../../types/work';

export type WorkMergeMetadata = Readonly<{
  title: string;
  author: string;
  description: string | null;
  seriesName: string | null;
  seriesIndex: number | null;
  tags: string[];
}>;

export type WorkMergeVolume = Readonly<{
  id: string;
  title: string;
  volumeIndex: number | null;
  format: string;
  sourceWorkId: string;
  sourceWorkTitle: string;
  coverUrl: string;
  hasCover: boolean;
}>;

export type WorkMergePreview = Readonly<{
  works: ReadonlyArray<Readonly<{ id: string; title: string; author: string }>>;
  mediaGroups: ReadonlyArray<Readonly<{ mediaKind: MediaKind; volumes: WorkMergeVolume[] }>>;
  suggestedMetadata: WorkMergeMetadata;
  defaultCoverVolumeId: string;
  writeMetadataToFiles: boolean;
}>;

export type WorkMergeResult = Readonly<{
  workId: string;
  sourceWorkIds: string[];
  operation: Readonly<{ summary: string; undoAvailable: boolean }>;
}>;

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`WORK_MERGE_INVALID_${field}`);
  return value;
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

async function mergeJson(path: string, body: unknown): Promise<Record<string, unknown>> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(body)
  });
  const payload = record(await response.json().catch(() => null));
  const error = record(payload.error);
  if (!response.ok || payload.ok !== true) {
    throw new Error(typeof error.message === 'string' ? error.message : '合并图书失败');
  }
  return record(payload.data);
}

export async function fetchWorkMergePreview(
  workIds: string[],
  signal?: AbortSignal
): Promise<WorkMergePreview> {
  const response = await fetch('/api/works/merge/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    signal,
    body: JSON.stringify({ workIds })
  });
  const payload = record(await response.json().catch(() => null));
  const error = record(payload.error);
  if (!response.ok || payload.ok !== true) {
    throw new Error(typeof error.message === 'string' ? error.message : '读取合并预览失败');
  }
  const data = record(payload.data);
  const metadata = record(data.suggestedMetadata);
  const works = Array.isArray(data.works) ? data.works.map((value) => {
    const work = record(value);
    return {
      id: stringValue(work.id, 'workId'),
      title: stringValue(work.title, 'workTitle'),
      author: stringValue(work.author, 'workAuthor')
    };
  }) : [];
  const mediaGroups = Array.isArray(data.mediaGroups) ? data.mediaGroups.map((value) => {
    const group = record(value);
    const mediaKind = group.mediaKind;
    if (mediaKind !== 'EBOOK' && mediaKind !== 'COMIC' && mediaKind !== 'AUDIOBOOK') {
      throw new Error('WORK_MERGE_INVALID_mediaKind');
    }
    const parsedMediaKind: MediaKind = mediaKind;
    const volumes = Array.isArray(group.volumes) ? group.volumes.map((entry) => {
      const volume = record(entry);
      return {
        id: stringValue(volume.id, 'volumeId'),
        title: stringValue(volume.title, 'volumeTitle'),
        volumeIndex: nullableNumber(volume.volumeIndex),
        format: stringValue(volume.format, 'volumeFormat'),
        sourceWorkId: stringValue(volume.sourceWorkId, 'sourceWorkId'),
        sourceWorkTitle: stringValue(volume.sourceWorkTitle, 'sourceWorkTitle'),
        coverUrl: stringValue(volume.coverUrl, 'coverUrl'),
        hasCover: volume.hasCover === true
      };
    }) : [];
    return { mediaKind: parsedMediaKind, volumes };
  }) : [];
  return {
    works,
    mediaGroups,
    suggestedMetadata: {
      title: stringValue(metadata.title, 'title'),
      author: stringValue(metadata.author, 'author'),
      description: nullableString(metadata.description),
      seriesName: nullableString(metadata.seriesName),
      seriesIndex: nullableNumber(metadata.seriesIndex),
      tags: Array.isArray(metadata.tags)
        ? metadata.tags.filter((tag): tag is string => typeof tag === 'string')
        : []
    },
    defaultCoverVolumeId: stringValue(data.defaultCoverVolumeId, 'defaultCoverVolumeId'),
    writeMetadataToFiles: data.writeMetadataToFiles === true
  };
}

export async function createWorkMerge(input: {
  workIds: string[];
  metadata: WorkMergeMetadata;
  coverVolumeId: string;
}): Promise<WorkMergeResult> {
  const data = await mergeJson('/api/works/merge', input);
  const operation = record(data.operation);
  return {
    workId: stringValue(data.workId, 'workId'),
    sourceWorkIds: Array.isArray(data.sourceWorkIds)
      ? data.sourceWorkIds.filter((value): value is string => typeof value === 'string')
      : [],
    operation: {
      summary: stringValue(operation.summary, 'operationSummary'),
      undoAvailable: operation.undoAvailable === true
    }
  };
}
