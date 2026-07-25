import type {
  AccountResponse,
  FileResponse,
  VolumeResponse,
  WorkDetailResponse,
  WorkResponse
} from '../../generated/api-v2';
import type {
  MediaKind,
  ReadingStatus,
  ReadingFormat,
  WorkView
} from '../../types/work';

export function accountCapabilities(account: AccountResponse) {
  return {
    isAdmin: account.role === 'admin',
    canManageSystem: account.scopes.includes('operations:write')
  };
}

function mediaKind(mediaType: string): MediaKind {
  if (mediaType === 'comic') return 'COMIC';
  if (mediaType === 'audiobook') return 'AUDIOBOOK';
  return 'EBOOK';
}

function readingFormat(format: string | undefined, kind: MediaKind): ReadingFormat {
  const normalized = format?.toUpperCase();
  if (
    normalized === 'EPUB'
    || normalized === 'PDF'
    || normalized === 'MOBI'
    || normalized === 'AZW'
    || normalized === 'AZW3'
    || normalized === 'PRC'
    || normalized === 'FB2'
    || normalized === 'TXT'
  ) {
    return normalized;
  }
  return kind === 'COMIC' ? 'COMIC' : kind === 'AUDIOBOOK' ? 'AUDIO' : 'EPUB';
}

function metadataString(
  metadata: Record<string, unknown>,
  key: string
): string | null {
  const value = metadata[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

function metadataNumber(
  metadata: Record<string, unknown>,
  key: string
): number | null {
  const value = metadata[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function metadataStrings(
  metadata: Record<string, unknown>,
  key: string
): string[] {
  const value = metadata[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

function readingStatus(metadata: Record<string, unknown>): ReadingStatus {
  const value = metadata.readingStatus;
  return value === 'READING' || value === 'FINISHED' ? value : 'UNREAD';
}

function readingStatusLabel(value: ReadingStatus): string {
  if (value === 'READING') return '进行中';
  if (value === 'FINISHED') return '已完成';
  return '未开始';
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? Math.round(amount) : amount.toFixed(1)} ${units[unit]}`;
}

function fileResponseToView(file: FileResponse): WorkView['files'][number] {
  return {
    id: file.id,
    editionId: file.editionId,
    volumeId: file.volumeId,
    path: file.originalName,
    mimeType: file.mediaType,
    kind: file.mediaType.startsWith('audio/') ? 'audio' : 'document',
    sortOrder: file.sortOrder,
    sizeBytes: file.sizeBytes,
    size: formatBytes(file.sizeBytes),
    durationMs: file.durationMs,
    url: `/api/v2/reading/files/${encodeURIComponent(file.id)}`
  };
}

function volumeResponseToView(
  volume: VolumeResponse,
  coverUrl: string
): WorkView['volumes'][number] {
  return {
    id: volume.id,
    editionId: volume.editionId,
    title: volume.title,
    volumeIndex: volume.sortOrder + 1,
    sortOrder: volume.sortOrder,
    pageCount: volume.pageCount,
    chapterCount: null,
    coverUrl,
    durationMs: volume.durationMs
  };
}

export function workResponseToView(
  work: WorkResponse | WorkDetailResponse
): WorkView {
  const kind = mediaKind(work.mediaType);
  const detail = 'editions' in work ? work : null;
  const primary = detail?.editions.find((edition) => edition.primary) ?? detail?.editions[0];
  const format = readingFormat(primary?.format, kind);
  const metadata = work.metadata;
  const workReadingStatus = readingStatus(metadata);
  const editions: WorkView['editions'] = (detail?.editions ?? []).map((edition) => {
    const editionMetadata = edition.metadata;
    const files = edition.files.map(fileResponseToView);
    const volumes = edition.volumes.map((volume) => (
      volumeResponseToView(volume, work.coverUrl ?? '')
    ));
    return {
      id: edition.id,
      workId: edition.workId,
      formatValue: readingFormat(edition.format, kind),
      mediaKind: kind,
      format: edition.format.toUpperCase(),
      versionName: edition.title,
      description: metadataString(editionMetadata, 'description'),
      publisher: metadataString(editionMetadata, 'publisher'),
      publishedAt: metadataString(editionMetadata, 'publishedAt'),
      language: edition.language,
      identifier: metadataString(editionMetadata, 'identifier'),
      isbn: metadataString(editionMetadata, 'isbn'),
      narrator: metadataString(editionMetadata, 'narrator'),
      primary: edition.primary,
      hidden: false,
      readable: true,
      conversionAvailable: false,
      size: formatBytes(edition.files.reduce((total, file) => total + file.sizeBytes, 0)),
      pageCount: edition.volumes.reduce<number | null>(
        (total, volume) => (
          total === null || volume.pageCount === null ? null : total + volume.pageCount
        ),
        0
      ),
      chapterCount: null,
      progress: 0,
      lastReadAt: null,
      coverUrl: work.coverUrl ?? '',
      conversion: null,
      files,
      volumes
    };
  });
  const files = editions.flatMap((edition) => edition.files);
  const volumes = editions.flatMap((edition) => edition.volumes);
  return {
    id: work.id,
    workId: work.id,
    editionId: primary?.id ?? null,
    monitorFolderId: null,
    title: work.title,
    author: work.author ?? '',
    publisher: metadataString(metadata, 'publisher'),
    type: kind === 'COMIC' ? 'comic' : kind === 'AUDIOBOOK' ? 'audiobook' : 'ebook',
    mediaKind: kind,
    formatValue: format,
    format,
    size: formatBytes(files.reduce((total, file) => total + file.sizeBytes, 0)),
    progress: 0,
    statusValue: workReadingStatus,
    status: readingStatusLabel(workReadingStatus),
    publicationStatusValue: 'UNKNOWN',
    publicationStatus: '未知',
    trackingStatusValue: 'NOT_TRACKING',
    trackingStatus: '未跟踪',
    localLatestVolume: null,
    localLatestChapter: null,
    localLatestTitle: null,
    localLatestAt: null,
    ignored: work.status === 'archived',
    organized: true,
    organizeStatus: 'ready',
    metadataQuality: 0,
    tags: metadataStrings(metadata, 'tags'),
    seriesName: metadataString(metadata, 'seriesName'),
    seriesIndex: metadataNumber(metadata, 'seriesIndex'),
    publishedYear: metadataNumber(metadata, 'publishedYear'),
    added: work.createdAt,
    lastRead: '—',
    lastReadAt: null,
    chapter: '',
    chapterCount: null,
    pageCount: volumes.reduce<number | null>(
      (total, volume) => total === null || volume.pageCount === null ? null : total + volume.pageCount,
      0
    ),
    desc: work.summary ?? '',
    path: '',
    fileHash: '',
    gradient: 'from-stone-100 to-stone-200',
    coverStatus: work.coverUrl ? 'ready' : 'missing',
    coverUrl: work.coverUrl ?? '',
    totalUnits: 0,
    readingProgress: 0,
    importStatus: 'completed',
    importError: null,
    importedAt: work.createdAt,
    files,
    versionCount: editions.length,
    volumeCount: volumes.length,
    primaryEditionId: primary?.id ?? null,
    primaryEditionName: primary?.title ?? null,
    recentEditionId: primary?.id ?? null,
    recentVolumeId: null,
    availableMediaKinds: [kind],
    defaultMediaKind: kind,
    detailTabs: [
      { key: kind, label: kind, sortOrder: 0 },
      { key: 'STRUCTURE', label: '内容结构', sortOrder: 1 }
    ],
    selectedDetailTab: kind,
    volumes,
    editions
  };
}
