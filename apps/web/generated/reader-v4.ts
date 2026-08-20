/* eslint-disable */
// AUTO-GENERATED from the Reader v4 FastAPI OpenAPI contract.
// Run `pnpm --filter @shuku/web generate:reader-api`; do not edit by hand.

export type AudioExactLocation_Input = {
  kind: "audio";
  fileId: string;
  chapterId?: string | null;
  positionMillis: number;
  engineLocator?: OpaqueReadiumEngineLocator_Input | null;
};

export type AudioExactLocation_Output = {
  kind: "audio";
  fileId: string;
  chapterId?: string | null;
  positionMillis: number;
  engineLocator?: OpaqueReadiumEngineLocator_Output | null;
};

export type AudioLocation = {
  kind: "audio";
  fileId: string;
  chapterId?: string | null;
  positionMs: number;
};

export type ComicExactLocation_Input = {
  kind: "comic";
  pageIndex: number;
  resourceHref: string;
  engineLocator?: OpaqueReadiumEngineLocator_Input | null;
};

export type ComicExactLocation_Output = {
  kind: "comic";
  pageIndex: number;
  resourceHref: string;
  engineLocator?: OpaqueReadiumEngineLocator_Output | null;
};

export type ComicLocation = {
  kind: "comic";
  pageIndex: number;
};

export type OpaqueReadiumEngineLocator_Input = {
  engine: "readium";
  platform: "android" | "ios" | "web";
  version: string;
  payload: {
    [key: string]: ReaderJsonValue_Input | null | undefined;
  };
};

export type OpaqueReadiumEngineLocator_Output = {
  engine: "readium";
  platform: "android" | "ios" | "web";
  version: string;
  payload: {
    [key: string]: ReaderJsonValue_Output | null | undefined;
  };
};

export type PdfExactLocation_Input = {
  kind: "pdf";
  pageIndex: number;
  pageProgression: number;
  engineLocator?: OpaqueReadiumEngineLocator_Input | null;
};

export type PdfExactLocation_Output = {
  kind: "pdf";
  pageIndex: number;
  pageProgression: number;
  engineLocator?: OpaqueReadiumEngineLocator_Output | null;
};

export type PdfLocation = {
  kind: "pdf";
  pageNumber: number;
};

export type ReaderBookSummary = {
  id: string;
  title: string;
  author?: string | null;
  coverUrl?: string | null;
};

export type ReaderBookmark = {
  id: string;
  location: ReflowLocation | ComicLocation | PdfLocation | AudioLocation;
  label: string;
  percent: number;
  createdAt: string;
};

export type ReaderBookmarksData = {
  bookmarks: Array<ReaderBookmark>;
};

export type ReaderBookmarksReplaceRequest = {
  bookmarks: Array<ReaderBookmark>;
};

export type ReaderBookmarksResponse = {
  ok?: true;
  data: ReaderBookmarksData;
};

export type ReaderBootstrapData = {
  schemaVersion?: 4;
  userId: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  sourceFormat: "epub" | "mobi" | "azw" | "azw3" | "prc" | "txt" | "cbz" | "zip" | "cbr" | "rar" | "pdf" | "audio" | "audiobook" | "m4b" | "m4a" | "mp3";
  book: ReaderBookSummary;
  version: ReaderVersionSchema;
  versionCompleted: boolean;
  volume: ReaderVolumeSummary;
  availableVolumes: Array<ReaderVolumeSummary>;
  files: Array<ReaderFileSummary>;
  units: Array<ReaderUnitSummary>;
  fileUrl: string;
  capabilities: ReaderCapabilities;
  publication?: ReaderPublicationAccess | null;
  progressSnapshot?: ReaderProgressSnapshot | null;
};

export type ReaderBootstrapResponse = {
  ok?: true;
  data: ReaderBootstrapData;
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

export type ReaderComicDownloadArtifact = {
  url: string;
  sourceFormat: "cbz" | "zip" | "cbr" | "rar";
  mimeType: string;
  sizeBytes: number;
};

export type ReaderComicManifestData = {
  schemaVersion?: 1;
  kind?: "comic";
  volumeId: string;
  sourceFormat: "cbz" | "zip" | "cbr" | "rar";
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

export type ReaderErrorBody = {
  message: string;
  code?: string | null;
  details?: {
    [key: string]: ReaderJsonValue_Output | null | undefined;
  } | null;
};

export type ReaderFileSummary = {
  id: string;
  kind: string;
  mimeType: string;
  sizeBytes: number;
  durationMs?: number | null;
  discNumber?: number | null;
  trackNumber?: number | null;
  sortOrder: number;
  url: string;
  codec?: string | null;
};

export type ReaderJsonValue_Input = string | number | boolean | Array<ReaderJsonValue_Input> | {
  [key: string]: ReaderJsonValue_Input | null | undefined;
} | null;

export type ReaderJsonValue_Output = string | number | boolean | Array<ReaderJsonValue_Output> | {
  [key: string]: ReaderJsonValue_Output | null | undefined;
} | null;

export type ReaderProgressConflictBody = {
  message: string;
  code?: "READER_PROGRESS_CONFLICT";
  current: ReaderProgressSnapshot;
};

export type ReaderProgressPut = {
  schemaVersion: 4;
  clientId: string;
  mutationId: string;
  baseRevision: number;
  capturedAtEpochMillis: number;
  locator: ReflowableExactLocation_Input | PdfExactLocation_Input | ComicExactLocation_Input | AudioExactLocation_Input;
};

export type ReaderProgressResponse = {
  ok?: true;
  data: ReaderProgressSnapshot;
};

export type ReaderProgressSnapshot = {
  schemaVersion?: 4;
  revision: number;
  clientId: string;
  locator: ReflowableExactLocation_Output | PdfExactLocation_Output | ComicExactLocation_Output | AudioExactLocation_Output;
  displayPercent: number;
  receivedAtEpochMillis: number;
  capturedAtEpochMillis?: number | null;
};

export type ReaderProgressStateData = {
  schemaVersion?: 4;
  progressSnapshot: ReaderProgressSnapshot | null;
};

export type ReaderProgressStateResponse = {
  ok?: true;
  data: ReaderProgressStateData;
};

export type ReaderPublicationAccess = {
  kind: "reflowable" | "comic";
  manifestUrl: string;
  positionsUrl?: string | null;
  pageUrlTemplate?: string | null;
  imageVariants?: Array<"original" | "data-saver">;
  downloadArtifact?: ReaderComicDownloadArtifact | null;
};

export type ReaderReadingStatusData = {
  volumeId: string;
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

export type ReaderUnitSummary = {
  id: string;
  index: number;
  title: string;
  href?: string | null;
  fileId?: string | null;
  startMs?: number | null;
  endMs?: number | null;
  durationMs?: number | null;
  metadata?: {
    [key: string]: ReaderJsonValue_Output | null | undefined;
  };
};

export type ReaderVersionSchema = {
  id: string;
  workId: string;
  sourceKey: string;
  sourceName?: string | null;
};

export type ReaderVolumeSummary = {
  id: string;
  versionId: string;
  title: string;
  volumeIndex?: number | null;
  sortOrder: number;
  format: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  pageCount?: number | null;
  chapterCount?: number | null;
  durationMs?: number | null;
  trackCount?: number | null;
  progress: number;
  lastReadAt?: string | null;
};

export type ReadiumEngineLocator_Input = {
  engine: "readium";
  platform: "android" | "ios" | "web";
  version: string;
  payload: ReadiumLocatorPayload_Input;
};

export type ReadiumEngineLocator_Output = {
  engine: "readium";
  platform: "android" | "ios" | "web";
  version: string;
  payload: ReadiumLocatorPayload_Output;
};

export type ReadiumLocatorLocations_Input = {
  cssSelector?: string | null;
  fragments?: Array<string>;
  progression?: number | null;
  totalProgression?: number | null;
  position?: number | null;
  [key: string]: ReaderJsonValue_Input | null | undefined;
};

export type ReadiumLocatorLocations_Output = {
  cssSelector?: string | null;
  fragments?: Array<string>;
  progression?: number | null;
  totalProgression?: number | null;
  position?: number | null;
  [key: string]: ReaderJsonValue_Output | null | undefined;
};

export type ReadiumLocatorPayload_Input = {
  href: string;
  type: string;
  title?: string | null;
  locations: ReadiumLocatorLocations_Input;
  text?: ReadiumLocatorText | null;
  [key: string]: ReaderJsonValue_Input | null | undefined;
};

export type ReadiumLocatorPayload_Output = {
  href: string;
  type: string;
  title?: string | null;
  locations: ReadiumLocatorLocations_Output;
  text?: ReadiumLocatorText | null;
  [key: string]: ReaderJsonValue_Output | null | undefined;
};

export type ReadiumLocatorText = {
  before?: string | null;
  highlight?: string | null;
  after?: string | null;
};

export type ReflowLocation = {
  kind: "reflow";
  resourceKey: string;
  progression?: number | null;
};

export type ReflowableExactLocation_Input = {
  kind: "reflowable";
  engineLocator: ReadiumEngineLocator_Input;
};

export type ReflowableExactLocation_Output = {
  kind: "reflowable";
  engineLocator: ReadiumEngineLocator_Output;
};
