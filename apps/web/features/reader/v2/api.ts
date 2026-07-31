import { normalizeReaderPreferences, type ReaderLocation, type ReaderSource } from '@shuku/reader-core';
import type {
  ComicLocation,
  EpubLocation,
  PdfLocation,
  ReflowableLocation,
  ReaderBootstrapData,
  ReaderBootstrapResponse,
  ReaderEditionOption,
  ReaderEditionSummary
} from '../../../generated/reader-v2';
import { withBasePath } from '../../../lib/base-path';
import type { ReaderBookmark } from './bookmarks';

type ReaderWireLocation = EpubLocation | ReflowableLocation | ComicLocation | PdfLocation;
type VisualReaderType = 'reflowable' | 'comic' | 'pdf';
type VisualReaderEdition = Omit<ReaderEditionSummary, 'format'> & { format: VisualReaderType };
type VisualReaderEditionOption = Omit<ReaderEditionOption, 'format'> & { format: VisualReaderType };
type VisualReaderBootstrapData = Omit<ReaderBootstrapData, 'readerType' | 'edition' | 'availableEditions' | 'resumeLocation'> & {
  readerType: VisualReaderType;
  edition: VisualReaderEdition;
  availableEditions: VisualReaderEditionOption[];
  resumeLocation?: ReaderWireLocation | null;
};
type ReaderErrorResponse = { ok?: false; error?: { code?: string; message?: string }; detail?: string };

export type ReaderBootstrap = Omit<VisualReaderBootstrapData, 'schemaVersion' | 'serverPreferences' | 'progressPercent' | 'resumeFingerprintMismatch'> & {
  schemaVersion: 2;
  progressPercent: number;
  resumeFingerprintMismatch: boolean;
  serverPreferences: Omit<ReaderBootstrapData['serverPreferences'], 'settings'> & {
    settings: import('@shuku/reader-core').ReaderPreferences;
  };
  source: ReaderSource;
  initialLocation: ReaderLocation | null;
};

function isVisualReaderType(value: ReaderBootstrapData['readerType'] | ReaderEditionSummary['format']): value is VisualReaderType {
  return value === 'reflowable' || value === 'comic' || value === 'pdf';
}

export function wireLocationToDomain(location: ReaderWireLocation | null | undefined): ReaderLocation | null {
  if (!location) return null;
  if (location.type === 'epub') {
    return {
      kind: 'reflowable',
      format: 'epub',
      cfi: location.cfi ?? undefined,
      href: location.href ?? undefined,
      progression: location.progression ?? undefined
    };
  }
  if (location.type === 'reflowable') {
    return {
      kind: 'reflowable',
      format: location.format,
      cfi: location.cfi ?? undefined,
      href: location.href ?? undefined,
      progression: location.progression ?? undefined
    };
  }
  if (location.type === 'comic') return { kind: 'comic', volumeId: location.volumeId, pageIndex: location.pageIndex };
  return { kind: 'pdf', pageNumber: location.pageNumber };
}

export async function fetchReaderBootstrap(
  editionId: string,
  volumeId: string | null,
  signal: AbortSignal
): Promise<ReaderBootstrap> {
  const query = new URLSearchParams();
  if (volumeId) query.set('volume', volumeId);
  const response = await fetch(`/api/reader/v2/editions/${encodeURIComponent(editionId)}/bootstrap${query.size ? `?${query}` : ''}`, {
    credentials: 'same-origin',
    cache: 'no-store',
    signal
  });
  const payload = await response.json().catch(() => null) as ReaderBootstrapResponse | ReaderErrorResponse | null;
  if (!response.ok || !payload || payload.ok !== true || !('data' in payload)) {
    const errorPayload = payload as ReaderErrorResponse | null;
    throw new Error(errorPayload?.error?.message ?? errorPayload?.detail ?? `读取阅读器启动信息失败（${response.status}）`);
  }
  const data = payload.data;
  const sourceFormat = data.sourceFormat;
  if (!isVisualReaderType(data.readerType) || !isVisualReaderType(data.edition.format)) {
    throw new Error('有声书请使用专用播放器打开');
  }
  const resumeLocation = data.resumeLocation;
  if (resumeLocation?.type === 'audio') throw new Error('有声书进度不能在图文阅读器中恢复');
  const selectedVolumeId = data.selectedVolume?.id ?? volumeId;
  const initialLocation = wireLocationToDomain(resumeLocation);
  const edition: VisualReaderEdition = { ...data.edition, format: data.edition.format };
  const availableEditions = data.availableEditions.filter((candidate): candidate is VisualReaderEditionOption => isVisualReaderType(candidate.format));
  let source: ReaderSource;
  if (data.readerType === 'reflowable') {
    if (!sourceFormat) throw new Error('小说阅读器启动信息缺少源格式');
    source = {
      editionId: data.edition.id,
      workId: data.edition.workId,
      kind: 'reflowable',
      sourceFormat,
      contentUrl: withBasePath(data.fileUrl),
      contentFingerprint: data.contentFingerprint,
      volumeId: selectedVolumeId,
      totalPages: data.totalPages ?? data.edition.pageCount ?? null
    };
  } else {
    source = {
      editionId: data.edition.id,
      workId: data.edition.workId,
      kind: data.readerType,
      contentUrl: withBasePath(data.fileUrl),
      contentFingerprint: data.contentFingerprint,
      volumeId: selectedVolumeId,
      totalPages: data.totalPages ?? data.edition.pageCount ?? null
    };
  }
  return {
    ...data,
    readerType: data.readerType,
    edition,
    availableEditions,
    resumeLocation,
    schemaVersion: 2,
    progressPercent: data.progressPercent ?? 0,
    resumeFingerprintMismatch: data.resumeFingerprintMismatch ?? false,
    serverPreferences: {
      ...data.serverPreferences,
      settings: normalizeReaderPreferences(data.serverPreferences.settings)
    },
    source,
    initialLocation
  };
}

export async function fetchReaderBookmarks(
  editionId: string,
  contentFingerprint: string,
  signal?: AbortSignal
): Promise<ReaderBookmark[]> {
  const query = new URLSearchParams({ contentFingerprint });
  const response = await fetch(
    `/api/reader/v2/editions/${encodeURIComponent(editionId)}/bookmarks?${query}`,
    { credentials: 'same-origin', cache: 'no-store', signal }
  );
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok || !Array.isArray(payload.data?.bookmarks)) {
    throw new Error(payload?.error?.message ?? '读取书签失败');
  }
  return payload.data.bookmarks as ReaderBookmark[];
}

export async function saveReaderBookmarks(
  editionId: string,
  contentFingerprint: string,
  bookmarks: ReaderBookmark[]
): Promise<ReaderBookmark[]> {
  const response = await fetch(`/api/reader/v2/editions/${encodeURIComponent(editionId)}/bookmarks`, {
    method: 'PUT',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ contentFingerprint, bookmarks })
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok || !Array.isArray(payload.data?.bookmarks)) {
    throw new Error(payload?.error?.message ?? '保存书签失败');
  }
  return payload.data.bookmarks as ReaderBookmark[];
}
