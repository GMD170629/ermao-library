import type { ServerBaseUrl } from '../../server-connection/public';

export type LibraryMediaKind = 'AUDIOBOOK' | 'COMIC' | 'EBOOK';
export type LibraryReadingStatus = 'FINISHED' | 'READING' | 'UNREAD';
export type LibraryView = 'grid' | 'list';
export type LibrarySort =
  | 'author'
  | 'recent_import'
  | 'recent_read'
  | 'series'
  | 'title';
export type LibrarySortDirection = 'asc' | 'desc';

export type LibraryFailure = Readonly<{
  reason:
    | 'cancelled'
    | 'forbidden'
    | 'incompatible-response'
    | 'invalid-request'
    | 'network'
    | 'not-found'
    | 'response-too-large'
    | 'session-expired'
    | 'timeout'
    | 'unknown';
  operation:
    | 'create-shelf'
    | 'delete-shelf'
    | 'import-files'
    | 'load-books'
    | 'load-collection'
    | 'load-cover'
    | 'load-home'
    | 'load-import-targets'
    | 'load-preferences'
    | 'load-shelves'
    | 'rename-shelf'
    | 'save-preferences';
  status?: number;
  code?: string;
}>;

export type LibraryBook = Readonly<{
  id: string;
  title: string;
  author: string;
  coverUrl: string;
  mediaKinds: readonly LibraryMediaKind[];
  progressPercent?: number;
}>;

export type ContinueReadingBook = LibraryBook &
  Readonly<{
    readerType: 'audio' | 'comic' | 'pdf' | 'reflowable';
    resumeVolumeId: string | null;
    progressPercent: number;
    chapter: string | null;
    volumeTitle: string | null;
    lastReadAt: string | null;
  }>;

export type HomeSummary = Readonly<{
  totalBooks: number;
  unreadBooks: number;
  ebookBooks: number;
  comicBooks: number;
  audiobookBooks: number;
}>;

export type HomeSection =
  | 'continue-reading'
  | 'recent-books'
  | 'recent-reading'
  | 'summary'
  | 'unread';

export type HomeData = Readonly<{
  summary: HomeSummary | null;
  continueReading: ContinueReadingBook | null;
  recentReading: readonly LibraryBook[];
  recentBooks: readonly LibraryBook[];
  unavailableSections: readonly HomeSection[];
}>;

export type HomeState =
  | Readonly<{ phase: 'idle' }>
  | Readonly<{ phase: 'loading' }>
  | Readonly<{
      phase: 'ready';
      data: HomeData;
      refreshing: boolean;
      warning?: LibraryFailure;
    }>
  | Readonly<{ phase: 'failure'; failure: LibraryFailure }>;

export type ShelfKind = 'COLLECTION' | 'SMART' | 'STATIC';

export type ShelfSummary = Readonly<{
  id: string;
  name: string;
  description: string | null;
  kind: ShelfKind;
  pinned: boolean;
  bookCount: number;
  shelfCount: number;
  books: readonly LibraryBook[];
  memberShelfIds: readonly string[];
  updatedAt: string;
}>;

export type ShelfOverviewData = Readonly<{
  collections: readonly ShelfSummary[];
  shelves: readonly ShelfSummary[];
}>;

export type ShelfOverviewState =
  | Readonly<{ phase: 'idle' }>
  | Readonly<{ phase: 'loading' }>
  | Readonly<{
      phase: 'ready';
      data: ShelfOverviewData;
      refreshing: boolean;
      mutatingShelfId: string | null;
      warning?: LibraryFailure;
    }>
  | Readonly<{ phase: 'failure'; failure: LibraryFailure }>;

export type CollectionDetail = Readonly<{
  id: string;
  name: string;
  shelves: readonly ShelfSummary[];
}>;

export type CollectionDetailState =
  | Readonly<{ phase: 'idle' }>
  | Readonly<{ phase: 'loading'; collectionId: string }>
  | Readonly<{ phase: 'ready'; data: CollectionDetail }>
  | Readonly<{
      phase: 'failure';
      collectionId: string;
      failure: LibraryFailure;
    }>;

export type BooksQuery = Readonly<{
  search: string;
  status: LibraryReadingStatus | null;
  mediaKind: LibraryMediaKind | null;
  sort: LibrarySort;
  direction: LibrarySortDirection;
  view: LibraryView;
  shelfId: string | null;
}>;

export const DEFAULT_BOOKS_QUERY: BooksQuery = {
  search: '',
  status: null,
  mediaKind: null,
  sort: 'recent_read',
  direction: 'desc',
  view: 'grid',
  shelfId: null,
};

export function normalizeBooksQuery(query: BooksQuery): BooksQuery {
  return {
    ...query,
    search: query.search.trim().slice(0, 200),
  };
}

export type BooksState =
  | Readonly<{ phase: 'idle'; query: BooksQuery }>
  | Readonly<{ phase: 'loading'; query: BooksQuery }>
  | Readonly<{
      phase: 'ready';
      query: BooksQuery;
      books: readonly LibraryBook[];
      page: number;
      pageSize: 24;
      total: number;
      totalPages: number;
      refreshing: boolean;
      loadingNextPage: boolean;
      warning?: LibraryFailure;
    }>
  | Readonly<{
      phase: 'failure';
      query: BooksQuery;
      failure: LibraryFailure;
    }>;

export type ImportTarget = Readonly<{
  folderId: string;
  name: string;
  rootPath: string;
  enabled: boolean;
}>;

export type ImportTargets = Readonly<{
  targets: readonly ImportTarget[];
  selectedTargetPath: string | null;
}>;

export type ImportSuccess = Readonly<{
  saved: number;
  autoImport: boolean;
  files: readonly Readonly<{
    name: string;
    sourcePath: string;
    sizeBytes: number;
    monitoringStatus: 'NOT_MONITORED' | 'WATCHING';
  }>[];
}>;

export type ImportState =
  | Readonly<{ phase: 'idle' }>
  | Readonly<{ phase: 'loading-targets' }>
  | Readonly<{
      phase: 'ready';
      targets: ImportTargets;
      upload:
        | Readonly<{ phase: 'idle' }>
        | Readonly<{ phase: 'uploading'; completedFiles: number; totalFiles: number }>
        | Readonly<{ phase: 'succeeded'; result: ImportSuccess }>
        | Readonly<{ phase: 'failed'; failure: LibraryFailure }>;
    }>
  | Readonly<{ phase: 'failure'; failure: LibraryFailure }>;

export type LibraryPreferences = Readonly<{
  view: LibraryView;
  sort: LibrarySort;
  direction: LibrarySortDirection;
}>;

export type LibraryCover = Readonly<{
  cacheKey: string;
  sourceUrl: string;
  contentType: 'image/jpeg' | 'image/png' | 'image/webp';
  bytes: Uint8Array;
}>;

export type LibraryCoverSource = Readonly<{
  cacheKey: string;
  uri: string;
}>;

export type LibraryCoverState =
  | Readonly<{ phase: 'loading' }>
  | Readonly<{ phase: 'ready'; source: LibraryCoverSource }>
  | Readonly<{ phase: 'failure'; failure: LibraryFailure }>;

export type LibraryContext = Readonly<{
  baseUrl: ServerBaseUrl;
  canImport: boolean;
}>;

export type LibrarySnapshot = Readonly<{
  home: HomeState;
  shelves: ShelfOverviewState;
  collection: CollectionDetailState;
  books: BooksState;
  import: ImportState;
  covers: Readonly<Record<string, LibraryCoverState>>;
}>;

const SUPPORTED_IMPORT_EXTENSIONS = new Set([
  'aac', 'ac3', 'adx', 'aif', 'aifc', 'aiff', 'amr', 'ape', 'aptx',
  'aptxhd', 'au', 'azw', 'azw3', 'caf', 'cbr', 'cbz', 'dff', 'dsf', 'dts',
  'eac3', 'epub', 'fb2', 'flac', 'g722', 'g726', 'gsm', 'lbc', 'm4a',
  'm4b', 'm4r', 'mka', 'mlp', 'mobi', 'mp2', 'mp3', 'mpc', 'oga', 'ogg',
  'oma', 'opus', 'pdf', 'prc', 'qcp', 'ra', 'rar', 'rf64', 'shn', 'snd',
  'sph', 'spx', 'tak', 'thd', 'tta', 'txt', 'voc', 'w64', 'wav', 'wave',
  'weba', 'wma', 'wv', 'xma', 'zip',
]);

export function isSupportedImportFileName(name: string): boolean {
  const normalized = name.trim().toLowerCase();
  const separator = normalized.lastIndexOf('.');
  return (
    separator > -1 &&
    separator < normalized.length - 1 &&
    SUPPORTED_IMPORT_EXTENSIONS.has(normalized.slice(separator + 1))
  );
}

export function isImportTargetPathWithinRoot(
  targetPath: string,
  rootPath: string,
): boolean {
  const normalizedRoot = rootPath.replace(/[\\/]+$/, '');
  if (normalizedRoot.length === 0) return false;
  if (targetPath === normalizedRoot) return true;
  if (!targetPath.startsWith(normalizedRoot)) return false;
  const separator = targetPath[normalizedRoot.length];
  return separator === '/' || separator === '\\';
}
