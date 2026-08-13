/* eslint-disable */
// AUTO-GENERATED from the Reader v4 FastAPI OpenAPI contract.
// Run `pnpm --filter @shuku/web generate:reader-api`; do not edit by hand.

export type AudioLocation = {
  kind: "audio";
  fileId: string;
  chapterId?: string | null;
  positionMs: number;
};

export type ComicLocation = {
  kind: "comic";
  pageIndex: number;
};

export type LocatorEnvelope_Input = {
  engine: "readium";
  platform: "android" | "ios" | "web";
  version: string;
  publication: PublicationFingerprint;
  payload: ReadiumLocatorPayload_Input;
};

export type LocatorEnvelope_Output = {
  engine: "readium";
  platform: "android" | "ios" | "web";
  version: string;
  publication: PublicationFingerprint;
  payload: ReadiumLocatorPayload_Output;
};

export type PdfLocation = {
  kind: "pdf";
  pageNumber: number;
};

export type PublicationFingerprint = {
  originalFileHash: string;
  parser: string;
  normalization: string;
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
  contentFingerprint: string;
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
  sourceFormat?: "epub" | "mobi" | "azw" | "azw3" | "prc" | "fb2" | "txt" | null;
  publicationFingerprint: PublicationFingerprint;
  book: ReaderBookSummary;
  mediaVersion: ReaderMediaVersionSummary;
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
  contentHash?: string | null;
};

export type ReaderJsonValue_Input = string | number | boolean | Array<ReaderJsonValue_Input> | {
  [key: string]: ReaderJsonValue_Input | null | undefined;
} | null;

export type ReaderJsonValue_Output = string | number | boolean | Array<ReaderJsonValue_Output> | {
  [key: string]: ReaderJsonValue_Output | null | undefined;
} | null;

export type ReaderMediaVersionSummary = {
  id: string;
  workId: string;
  mediaKind: "EBOOK" | "COMIC" | "AUDIOBOOK";
  completed: boolean;
};

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
  locator: LocatorEnvelope_Input;
};

export type ReaderProgressResponse = {
  ok?: true;
  data: ReaderProgressSnapshot;
};

export type ReaderProgressSnapshot = {
  schemaVersion?: 4;
  revision: number;
  locator: LocatorEnvelope_Output;
  displayPercent: number;
  receivedAtEpochMillis: number;
  capturedAtEpochMillis?: number | null;
};

export type ReaderPublicationAccess = {
  manifestUrl: string;
  positionsUrl: string;
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

export type ReaderVolumeSummary = {
  id: string;
  mediaVersionId: string;
  title: string;
  volumeIndex?: number | null;
  sortOrder: number;
  format: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  derivedFromVolumeId?: string | null;
  pageCount?: number | null;
  chapterCount?: number | null;
  durationMs?: number | null;
  trackCount?: number | null;
  progress: number;
  lastReadAt?: string | null;
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
