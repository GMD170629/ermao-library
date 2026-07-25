import type {
  AccountResponse,
  WorkDetailResponse,
  WorkResponse
} from '../../generated/api-v2';
import type {
  MediaKind,
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

export function workResponseToView(
  work: WorkResponse | WorkDetailResponse
): WorkView {
  const kind = mediaKind(work.mediaType);
  const detail = 'editions' in work ? work : null;
  const primary = detail?.editions.find((edition) => edition.primary) ?? detail?.editions[0];
  const format = readingFormat(primary?.format, kind);
  const editions: WorkView['editions'] = (detail?.editions ?? []).map((edition) => ({
    id: edition.id,
    workId: edition.workId,
    formatValue: readingFormat(edition.format, kind),
    mediaKind: kind,
    format: edition.format.toUpperCase(),
    versionName: edition.title,
    language: edition.language,
    primary: edition.primary,
    hidden: false,
    readable: true,
    conversionAvailable: false,
    size: '—',
    pageCount: null,
    chapterCount: null,
    progress: 0,
    lastReadAt: null,
    coverUrl: work.coverUrl ?? '',
    conversion: null,
    files: [],
    volumes: []
  }));
  return {
    id: work.id,
    workId: work.id,
    editionId: primary?.id ?? null,
    monitorFolderId: null,
    title: work.title,
    author: work.author ?? '',
    publisher: null,
    type: kind === 'COMIC' ? 'comic' : kind === 'AUDIOBOOK' ? 'audiobook' : 'ebook',
    mediaKind: kind,
    formatValue: format,
    format,
    size: '—',
    progress: 0,
    statusValue: 'UNREAD',
    status: '未开始',
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
    tags: [],
    seriesName: null,
    seriesIndex: null,
    publishedYear: null,
    added: work.createdAt,
    lastRead: '—',
    lastReadAt: null,
    chapter: '',
    chapterCount: null,
    pageCount: null,
    desc: '',
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
    files: [],
    versionCount: editions.length,
    volumeCount: 0,
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
    volumes: [],
    editions
  };
}
