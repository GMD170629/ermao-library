import type {
  CancellationToken,
  ServerBaseUrl,
} from '../../server-connection/public';
import type {
  BooksQuery,
  CollectionDetail,
  ContinueReadingBook,
  HomeSection,
  HomeSummary,
  ImportSuccess,
  ImportTargets,
  LibraryBook,
  LibraryCover,
  LibraryCoverSource,
  LibraryFailure,
  LibraryPreferences,
  ShelfOverviewData,
  ShelfSummary,
} from '../model/library';

export type LibraryResult<Value> =
  | Readonly<{ outcome: 'loaded'; value: Value }>
  | Readonly<{ outcome: 'failed'; failure: LibraryFailure }>;

export type ShelfMutationOutcome =
  | Readonly<{ outcome: 'succeeded' }>
  | Readonly<{ outcome: 'failed'; failure: LibraryFailure }>;

export type HomeLoadResult = LibraryResult<
  Readonly<{
    summary: HomeSummary | null;
    continueReading: ContinueReadingBook | null;
    recentReading: readonly LibraryBook[];
    recentBooks: readonly LibraryBook[];
    unavailableSections: readonly HomeSection[];
  }>
>;

export type LibraryImportFile = Readonly<{
  name: string;
  mimeType?: string;
  sizeBytes?: number;
  content: Blob;
}>;

export type LibraryFilePickerResult =
  | Readonly<{ outcome: 'cancelled' }>
  | Readonly<{ outcome: 'selected'; files: readonly LibraryImportFile[] }>
  | Readonly<{ outcome: 'failed'; reason: string }>;

export interface LibraryFilePicker {
  pickFiles(): Promise<LibraryFilePickerResult>;
}

export type LibraryCoverStoreResult =
  | Readonly<{ outcome: 'stored'; source: LibraryCoverSource }>
  | Readonly<{ outcome: 'failed'; reason: string }>;

export interface LibraryCoverStore {
  store(cover: LibraryCover): Promise<LibraryCoverStoreResult>;
  clearServer(serverCachePrefix: string): Promise<void>;
}

export type BooksPage = Readonly<{
  books: readonly LibraryBook[];
  page: number;
  pageSize: 24;
  total: number;
  totalPages: number;
}>;

export interface LibraryGateway {
  loadHome(
    baseUrl: ServerBaseUrl,
    cancellation: CancellationToken,
  ): Promise<HomeLoadResult>;
  loadShelves(
    baseUrl: ServerBaseUrl,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ShelfOverviewData>>;
  loadCollection(
    baseUrl: ServerBaseUrl,
    collectionId: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<CollectionDetail>>;
  loadBooks(
    baseUrl: ServerBaseUrl,
    query: BooksQuery,
    page: number,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<BooksPage>>;
  loadPreferences(
    baseUrl: ServerBaseUrl,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<LibraryPreferences>>;
  savePreferences(
    baseUrl: ServerBaseUrl,
    preferences: LibraryPreferences,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<LibraryPreferences>>;
  createShelf(
    baseUrl: ServerBaseUrl,
    name: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ShelfSummary>>;
  renameShelf(
    baseUrl: ServerBaseUrl,
    shelfId: string,
    name: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ShelfSummary>>;
  deleteShelf(
    baseUrl: ServerBaseUrl,
    shelfId: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<Readonly<{ id: string }>>>;
  loadImportTargets(
    baseUrl: ServerBaseUrl,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ImportTargets>>;
  importFiles(
    baseUrl: ServerBaseUrl,
    files: readonly LibraryImportFile[],
    targetPath: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ImportSuccess>>;
  loadCover(
    baseUrl: ServerBaseUrl,
    coverUrl: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<LibraryCover>>;
  clearCoverCache(baseUrl?: ServerBaseUrl): void;
}

export interface LibraryCancellationSource {
  readonly token: CancellationToken;
  cancel(): void;
}

export interface LibraryCancellationFactory {
  create(): LibraryCancellationSource;
}
