import type { MediaKind, ReaderType } from '../../../types/work';

export type ContinueReadingItem = Readonly<{
  workId: string;
  title: string;
  author: string;
  coverUrl: string;
  mediaKind: MediaKind;
  volumeFormat: string;
  readerType: ReaderType;
  resumeVolumeId: string | null;
  progress: number;
  lastReadAt: string | null;
  chapter: string | null;
  volumeTitle: string | null;
  narrator: string | null;
}>;

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function mediaKind(value: unknown): MediaKind | null {
  return value === 'EBOOK' || value === 'COMIC' || value === 'AUDIOBOOK' ? value : null;
}

function readerType(value: unknown): ReaderType | null {
  return value === 'reflowable' || value === 'comic' || value === 'pdf' || value === 'audio' ? value : null;
}

export function mapContinueReadingItem(value: unknown): ContinueReadingItem | null {
  if (value === null) return null;
  const item = record(value);
  const workId = stringValue(item.workId).trim();
  const kind = mediaKind(item.mediaKind);
  const reader = readerType(item.readerType);
  if (!workId || !kind || !reader) return null;
  const progress = typeof item.progress === 'number' && Number.isFinite(item.progress)
    ? Math.max(0, Math.min(100, item.progress))
    : 0;
  return {
    workId,
    title: stringValue(item.title),
    author: stringValue(item.author),
    coverUrl: stringValue(item.coverUrl),
    mediaKind: kind,
    volumeFormat: stringValue(item.volumeFormat),
    readerType: reader,
    resumeVolumeId: nullableString(item.resumeVolumeId),
    progress,
    lastReadAt: nullableString(item.lastReadAt),
    chapter: nullableString(item.chapter),
    volumeTitle: nullableString(item.volumeTitle),
    narrator: nullableString(item.narrator)
  };
}
