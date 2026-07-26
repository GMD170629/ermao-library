import { apiV2Fetch } from '@/lib/api-v2';
import { normalizeReaderPreferences, type ReaderLocation, type ReaderSource } from '@shuku/reader-core';
import type {
  BookmarkResponse as ApiBookmarkResponse,
  BootstrapResponse as ApiBootstrapResponse,
  ProblemDetails
} from '../../../generated/api-v2';
import type {
  ComicLocation,
  EpubLocation,
  PdfLocation,
  ReaderBootstrapData,
  ReaderEditionOption,
  ReaderEditionSummary
} from '../../../generated/reader-v2';
import { withBasePath } from '../../../lib/base-path';
import type { ReaderBookmark } from './bookmarks';

type ReaderWireLocation = EpubLocation | ComicLocation | PdfLocation;
type VisualReaderType = 'epub' | 'comic' | 'pdf';
type VisualReaderEdition = Omit<ReaderEditionSummary, 'format'> & { format: VisualReaderType };
type VisualReaderEditionOption = Omit<ReaderEditionOption, 'format'> & { format: VisualReaderType };
type VisualReaderBootstrapData = Omit<
  ReaderBootstrapData,
  'readerType' | 'edition' | 'availableEditions' | 'resumeLocation'
> & {
  readerType: VisualReaderType;
  edition: VisualReaderEdition;
  availableEditions: VisualReaderEditionOption[];
  resumeLocation?: ReaderWireLocation | null;
};

export type ReaderBootstrap = Omit<
  VisualReaderBootstrapData,
  'schemaVersion' | 'serverPreferences' | 'progressPercent' | 'resumeFingerprintMismatch'
> & {
  schemaVersion: 2;
  progressPercent: number;
  resumeFingerprintMismatch: boolean;
  serverPreferences: Omit<ReaderBootstrapData['serverPreferences'], 'settings'> & {
    settings: import('@shuku/reader-core').ReaderPreferences;
  };
  source: ReaderSource;
  initialLocation: ReaderLocation | null;
};

function normalizeVisualReaderType(value: string): VisualReaderType | null {
  const normalized = value.toLowerCase();
  if (normalized === 'epub') return 'epub';
  if (['comic', 'cbz', 'cbr'].includes(normalized)) return 'comic';
  if (normalized === 'pdf') return 'pdf';
  return null;
}

export function wireLocationToDomain(location: ReaderWireLocation | null | undefined): ReaderLocation | null {
  if (!location) return null;
  if (location.type === 'epub') {
    return {
      kind: 'epub',
      cfi: location.cfi ?? undefined,
      href: location.href ?? undefined,
      spineIndex: location.spineIndex ?? undefined,
      progression: location.progression ?? undefined
    };
  }
  if (location.type === 'comic') {
    return { kind: 'comic', volumeId: location.volumeId, pageIndex: location.pageIndex };
  }
  return { kind: 'pdf', pageNumber: location.pageNumber };
}

function domainLocationToWire(location: ReaderLocation): ReaderWireLocation {
  if (location.kind === 'comic') {
    return { type: 'comic', volumeId: location.volumeId, pageIndex: location.pageIndex };
  }
  if (location.kind === 'pdf') return { type: 'pdf', pageNumber: location.pageNumber };
  return {
    type: 'epub',
    cfi: location.cfi ?? null,
    href: location.href ?? null,
    spineIndex: location.spineIndex ?? null,
    progression: location.progression ?? null
  };
}

function bookmarkFromApi(value: ApiBookmarkResponse): ReaderBookmark | null {
  const rawLocation = value.position.location ?? value.position;
  const location = wireLocationToDomain(rawLocation as ReaderWireLocation);
  if (!location) return null;
  return {
    id: value.clientId,
    location,
    label: value.label ?? '',
    percent: typeof value.position.percent === 'number' ? value.position.percent : 0,
    createdAt: value.createdAt
  };
}

export async function fetchReaderBootstrap(
  editionId: string,
  volumeId: string | null,
  signal: AbortSignal
): Promise<ReaderBootstrap> {
  const response = await apiV2Fetch(
    `/api/v2/reading/editions/${encodeURIComponent(editionId)}/bootstrap`,
    { credentials: 'same-origin', cache: 'no-store', signal }
  );
  const payload = await response.json().catch(() => null) as ApiBootstrapResponse | ProblemDetails | null;
  if (!response.ok || !payload || !('target' in payload)) {
    const problem = payload as ProblemDetails | null;
    throw new Error(problem?.detail ?? `读取阅读器启动信息失败（${response.status}）`);
  }
  const readerType = normalizeVisualReaderType(payload.target.format);
  if (!readerType) throw new Error('有声书请使用专用播放器打开');

  const rawResume = payload.progress?.position.location ?? payload.progress?.position;
  const resumeLocation = rawResume ? rawResume as ReaderWireLocation : null;
  const initialLocation = wireLocationToDomain(resumeLocation);
  const progressPercent = (payload.progress?.percentage ?? 0) * 100;
  const volumes = payload.volumes.map((volume) => ({
    id: volume.id,
    title: volume.title,
    index: volume.sortOrder + 1,
    pageCount: volume.pageCount,
    chapterCount: null
  }));
  const selectedFile = payload.files.find((file) => file.id === payload.target.fileId);
  const selectedVolumeId = volumeId ?? selectedFile?.volumeId ?? null;
  const selectedVolume = volumes.find((volume) => volume.id === selectedVolumeId)
    ?? (readerType === 'comic' ? volumes[0] ?? null : null);
  const totalPages = selectedVolume?.pageCount
    ?? (payload.pages.length > 0 ? payload.pages.length : null);
  const edition: VisualReaderEdition = {
    id: payload.target.editionId,
    workId: payload.target.workId,
    format: readerType,
    versionName: payload.target.editionTitle,
    pageCount: totalPages,
    chapterCount: payload.units.length || null
  };
  const availableEditions: VisualReaderEditionOption[] = [{
    ...edition,
    progress: progressPercent,
    lastReadAt: payload.progress?.updatedAt ?? null,
    volumes
  }];
  return {
    userId: payload.accountId,
    readerType,
    contentFingerprint: payload.target.checksum,
    book: {
      id: payload.target.workId,
      title: payload.target.workTitle,
      author: payload.target.workAuthor,
      coverUrl: null
    },
    edition,
    availableEditions,
    selectedVolume,
    volumes,
    units: payload.units,
    pages: payload.pages,
    totalPages,
    fileUrl: payload.target.resourceUrl,
    capabilities: {
      canGoNext: true,
      canGoPrevious: true,
      canJumpToProgress: true,
      canJumpToHref: readerType === 'epub',
      canJumpToIndex: readerType !== 'epub',
      canZoom: readerType !== 'epub',
      canSelectText: readerType !== 'comic',
      supportsPagination: true,
      supportsScrolling: readerType !== 'comic',
      supportsSpreads: readerType !== 'pdf',
      readingDirection: 'ltr'
    },
    resumeLocation,
    schemaVersion: 2,
    progressPercent,
    resumeFingerprintMismatch: false,
    serverPreferences: {
      schemaVersion: 3,
      settings: normalizeReaderPreferences(payload.preference?.values ?? {}),
      updatedAt: payload.preference?.updatedAt ?? null
    },
    source: {
      editionId: payload.target.editionId,
      workId: payload.target.workId,
      kind: readerType,
      contentUrl: withBasePath(payload.target.resourceUrl),
      contentFingerprint: payload.target.checksum,
      volumeId: selectedVolume?.id ?? null,
      totalPages
    },
    initialLocation
  };
}

export async function fetchReaderBookmarks(
  editionId: string,
  contentFingerprint: string,
  signal?: AbortSignal
): Promise<ReaderBookmark[]> {
  const query = new URLSearchParams({ contentFingerprint });
  const response = await apiV2Fetch(
    `/api/v2/reading/editions/${encodeURIComponent(editionId)}/bookmarks?${query}`,
    { credentials: 'same-origin', cache: 'no-store', signal }
  );
  const payload = await response.json().catch(() => null) as {
    items?: ApiBookmarkResponse[];
    detail?: string;
  } | null;
  if (!response.ok || !Array.isArray(payload?.items)) {
    throw new Error(payload?.detail ?? '读取书签失败');
  }
  return payload.items
    .map(bookmarkFromApi)
    .filter((bookmark): bookmark is ReaderBookmark => bookmark !== null);
}

export async function saveReaderBookmarks(
  editionId: string,
  contentFingerprint: string,
  bookmarks: ReaderBookmark[]
): Promise<ReaderBookmark[]> {
  const baseUrl = `/api/v2/reading/editions/${encodeURIComponent(editionId)}/bookmarks`;
  const currentResponse = await apiV2Fetch(baseUrl, {
    credentials: 'same-origin',
    cache: 'no-store'
  });
  const currentPayload = await currentResponse.json().catch(() => null) as {
    items?: ApiBookmarkResponse[];
    detail?: string;
  } | null;
  if (!currentResponse.ok || !Array.isArray(currentPayload?.items)) {
    throw new Error(currentPayload?.detail ?? '读取书签失败');
  }

  const desiredIds = new Set(bookmarks.map((bookmark) => bookmark.id));
  for (const stored of currentPayload.items) {
    if (desiredIds.has(stored.clientId)) continue;
    const response = await apiV2Fetch(`${baseUrl}/${encodeURIComponent(stored.id)}`, {
      method: 'DELETE',
      credentials: 'same-origin'
    });
    if (!response.ok && response.status !== 404) {
      const problem = await response.json().catch(() => null) as ProblemDetails | null;
      throw new Error(problem?.detail ?? '删除书签失败');
    }
  }

  for (const bookmark of bookmarks) {
    const response = await apiV2Fetch(baseUrl, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        clientId: bookmark.id,
        label: bookmark.label,
        position: {
          location: domainLocationToWire(bookmark.location),
          percent: bookmark.percent,
          contentFingerprint
        }
      })
    });
    if (!response.ok) {
      const problem = await response.json().catch(() => null) as ProblemDetails | null;
      throw new Error(problem?.detail ?? '保存书签失败');
    }
  }
  return bookmarks;
}
