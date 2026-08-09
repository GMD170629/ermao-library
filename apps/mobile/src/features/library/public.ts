export { AbortLibraryCancellationFactory } from './api/abort-library-cancellation';
export { LibraryClient } from './api/library-client';
export {
  ExpoLibraryFilePicker,
  type ExpoLibraryFilePickerFunction,
  type ExpoLibraryFilePickerResult,
} from './infrastructure/expo-library-file-picker';
export {
  ExpoLibraryCoverFileSystem,
  ExpoLibraryCoverStore,
  type LibraryCoverFileSystem,
} from './infrastructure/expo-library-cover-store';
export {
  LibraryProvider,
  useLibrary,
  type LibraryContextValue,
  type LibraryProviderProps,
} from './ui/library-provider';
export {
  LibraryHomeScreen,
  type LibraryHomeScreenProps,
} from './ui/library-home-screen';
export {
  BookshelfScreen,
  type BookshelfScreenProps,
} from './ui/bookshelf-screen';
export {
  BooksScreen,
  type BooksScreenProps,
} from './ui/books-screen';
export {
  LibraryImportModal,
  type LibraryImportModalProps,
} from './ui/library-import-modal';
export {
  booksQueriesMatch,
  booksRouteParametersMatch,
  decodeBooksRouteQuery,
  encodeBooksRouteQuery,
  type BooksRouteParameters,
  type EncodedBooksRouteParameters,
} from './ui/books-route-query';
export {
  decodeBooksPage,
  decodeContinueReading,
  decodeCollectionDetail,
  decodeDashboardSummary,
  decodeDeletedShelf,
  decodeImportSuccess,
  decodeImportTargets,
  decodeLibraryErrorCode,
  decodePreferences,
  decodeRecentBooks,
  decodeShelf,
  decodeShelves,
  decodeUnreadTotal,
} from './api/library-schema';
export {
  LibraryController,
  type LibraryControllerOptions,
} from './application/library-controller';
export type {
  BooksPage,
  HomeLoadResult,
  LibraryCancellationFactory,
  LibraryCancellationSource,
  LibraryCoverStore,
  LibraryCoverStoreResult,
  LibraryFilePicker,
  LibraryFilePickerResult,
  LibraryGateway,
  LibraryImportFile,
  LibraryResult,
  ShelfMutationOutcome,
} from './application/ports';
export {
  DEFAULT_BOOKS_QUERY,
  isImportTargetPathWithinRoot,
  isSupportedImportFileName,
  normalizeBooksQuery,
} from './model/library';
export type {
  BooksQuery,
  BooksState,
  CollectionDetail,
  CollectionDetailState,
  ContinueReadingBook,
  HomeData,
  HomeSection,
  HomeState,
  HomeSummary,
  ImportState,
  ImportSuccess,
  ImportTarget,
  ImportTargets,
  LibraryBook,
  LibraryContext,
  LibraryCover,
  LibraryCoverSource,
  LibraryCoverState,
  LibraryFailure,
  LibraryMediaKind,
  LibraryPreferences,
  LibraryReadingStatus,
  LibrarySnapshot,
  LibrarySort,
  LibrarySortDirection,
  LibraryView,
  ShelfKind,
  ShelfOverviewData,
  ShelfOverviewState,
  ShelfSummary,
} from './model/library';
