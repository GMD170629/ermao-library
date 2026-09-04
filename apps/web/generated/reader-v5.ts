/* eslint-disable */
// AUTO-GENERATED from the Reader v5 FastAPI OpenAPI contract.
// Run `pnpm --filter @shuku/web generate:reader-api`; do not edit by hand.

export type ReaderAssetSummary = {
  id: string;
  title: string;
  resourceId: string;
  sourceNodeId: string;
  role: string;
  mimeType: string;
  sizeBytes: number;
  durationMs?: number | null;
  discNumber?: number | null;
  trackNumber?: number | null;
  sortOrder: number;
  url: string;
  codec?: string | null;
};

export type ReaderBookSummary = {
  id: string;
  title: string;
  author?: string | null;
  coverUrl?: string | null;
};

export type ReaderCapabilities = {
  canGoNext: boolean;
  canGoPrevious: boolean;
  canJumpToProgress: boolean;
  canJumpToHref: boolean;
  canJumpToIndex: boolean;
  canZoom: boolean;
  canSelectText: boolean;
  supportsPagination: boolean;
  supportsScrolling: boolean;
  supportsSpreads: boolean;
};

export type ReaderComicManifestData = {
  schemaVersion?: 2;
  kind?: "comic";
  resourceId: string;
  revision: string;
  sourceFormat: "cbz" | "zip" | "cbr" | "rar" | "image_dir";
  pageCount: number;
  readingOrder: Array<ReaderComicManifestPage>;
};

export type ReaderComicManifestPage = {
  pageIndex: number;
  resourceHref: string;
  title?: string | null;
  mediaType: string;
  width?: number | null;
  height?: number | null;
  sizeBytes?: number | null;
};

export type ReaderComicManifestResponse = {
  ok?: true;
  data: ReaderComicManifestData;
};

export type ReaderJsonValue = string | number | boolean | Array<ReaderJsonValue> | {
  [key: string]: ReaderJsonValue | null | undefined;
} | null;

export type ReaderNavigationUnitSummary = {
  id: string;
  index: number;
  title: string;
  href?: string | null;
  assetId?: string | null;
  startMs?: number | null;
  endMs?: number | null;
  durationMs?: number | null;
  metadata?: {
    [key: string]: ReaderJsonValue | null | undefined;
  };
};

export type ReaderPublicationAccess = {
  kind: "comic";
  manifestUrl: string;
  positionsUrl?: string | null;
  pageUrlTemplate?: string | null;
  imageVariants?: Array<"original" | "data-saver">;
};

export type ReaderReadingStatusData = {
  resourceId: string;
  status: "UNREAD" | "FINISHED";
  percent: number;
};

export type ReaderReadingStatusPut = {
  status: "UNREAD" | "FINISHED";
};

export type ReaderReadingStatusResponse = {
  ok?: true;
  data: ReaderReadingStatusData;
};

export type ReaderResourceSummary = {
  id: string;
  bookId: string;
  sourceNodeId: string;
  title: string;
  resourceIndex?: number | null;
  sortOrder: number;
  format: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  pageCount?: number | null;
  chapterCount?: number | null;
  durationMs?: number | null;
  trackCount?: number | null;
  progress: number;
  resourceCompleted: boolean;
  lastReadAt?: string | null;
};

export type ReaderV5Bookmark_Input = {
  id: string;
  position: ReaderV5Position_Input;
  label: string;
  createdAt: string;
};

export type ReaderV5Bookmark_Output = {
  id: string;
  position: ReaderV5Position_Output;
  label: string;
  createdAt: string;
};

export type ReaderV5BookmarksData = {
  bookmarks: Array<ReaderV5Bookmark_Output>;
};

export type ReaderV5BookmarksReplaceRequest = {
  bookmarks: Array<ReaderV5Bookmark_Input>;
};

export type ReaderV5BookmarksResponse = {
  ok: true;
  data: ReaderV5BookmarksData;
};

export type ReaderV5BootstrapData = {
  schemaVersion?: 5;
  userId: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  sourceFormat: "epub" | "mobi" | "azw" | "azw3" | "prc" | "txt" | "fb2" | "cbz" | "zip" | "cbr" | "rar" | "image_dir" | "pdf" | "audio" | "audiobook" | "audiobook_dir" | "m4b" | "m4a" | "mp3";
  book: ReaderBookSummary;
  resource: ReaderResourceSummary;
  availableResources: Array<ReaderResourceSummary>;
  assets: Array<ReaderAssetSummary>;
  units: Array<ReaderNavigationUnitSummary>;
  resourceUrl: string;
  capabilities: ReaderCapabilities;
  publication?: ReaderPublicationAccess | null;
  progressSnapshot?: ReaderV5ProgressSnapshot | null;
};

export type ReaderV5BootstrapResponse = {
  ok: true;
  data: ReaderV5BootstrapData;
};

export type ReaderV5Chapter = {
  href: string | null;
  title: string | null;
  index: number | null;
};

export type ReaderV5ErrorBody = {
  message: string;
  code?: string | null;
};

export type ReaderV5JsonValue_Input = string | number | boolean | Array<ReaderV5JsonValue_Input> | {
  [key: string]: ReaderV5JsonValue_Input | null | undefined;
} | null;

export type ReaderV5JsonValue_Output = string | number | boolean | Array<ReaderV5JsonValue_Output> | {
  [key: string]: ReaderV5JsonValue_Output | null | undefined;
} | null;

export type ReaderV5MutationReuseBody = {
  message: string;
  code?: "READER_PROGRESS_MUTATION_REUSE";
};

export type ReaderV5Page = {
  number: number;
  total: number | null;
};

export type ReaderV5Playback = {
  positionMillis: number;
  durationMillis: number | null;
};

export type ReaderV5Position_Input = {
  locator: {
    [key: string]: ReaderV5JsonValue_Input | null | undefined;
  };
  presentation: ReaderV5Presentation;
};

export type ReaderV5Position_Output = {
  locator: {
    [key: string]: ReaderV5JsonValue_Output | null | undefined;
  };
  presentation: ReaderV5Presentation;
};

export type ReaderV5Presentation = {
  displayPercent: number;
  totalProgression: number;
  currentHref: string | null;
  chapter: ReaderV5Chapter | null;
  page: ReaderV5Page | null;
  playback: ReaderV5Playback | null;
};

export type ReaderV5ProgressPut = {
  schemaVersion: 5;
  clientId: string;
  mutationId: string;
  capturedAtEpochMillis: number;
  position: ReaderV5Position_Input;
};

export type ReaderV5ProgressSnapshot = {
  schemaVersion: 5;
  revision: number;
  clientId: string;
  mutationId: string;
  capturedAtEpochMillis: number;
  receivedAtEpochMillis: number;
  position: ReaderV5Position_Output;
};

export type ReaderV5ProgressStateData = {
  schemaVersion: 5;
  progressSnapshot: ReaderV5ProgressSnapshot | null;
};

export type ReaderV5ProgressStateResponse = {
  ok: true;
  data: ReaderV5ProgressStateData;
};

export type ReaderV5ProgressWriteData = {
  acceptedMutationId: string;
  acceptedRevision: number;
  currentSnapshot: ReaderV5ProgressSnapshot;
};

export type ReaderV5ProgressWriteResponse = {
  ok: true;
  data: ReaderV5ProgressWriteData;
};
