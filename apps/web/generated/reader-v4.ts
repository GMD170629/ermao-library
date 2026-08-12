/* eslint-disable */
// AUTO-GENERATED from the Reader v4 FastAPI OpenAPI contract.
// Run `pnpm --filter @shuku/web generate:reader-api`; do not edit by hand.

export type AudioLocation_Input = {
  kind: "audio";
  fileId: string;
  chapterId?: string | null;
  positionMs: number;
  engineLocator?: ReaderEngineLocator_Input | null;
};

export type AudioLocation_Output = {
  kind: "audio";
  fileId: string;
  chapterId?: string | null;
  positionMs: number;
  engineLocator?: ReaderEngineLocator_Output | null;
};

export type ComicLocation_Input = {
  kind: "comic";
  pageIndex: number;
  engineLocator?: ReaderEngineLocator_Input | null;
};

export type ComicLocation_Output = {
  kind: "comic";
  pageIndex: number;
  engineLocator?: ReaderEngineLocator_Output | null;
};

export type PdfLocation_Input = {
  kind: "pdf";
  pageNumber: number;
  engineLocator?: ReaderEngineLocator_Input | null;
};

export type PdfLocation_Output = {
  kind: "pdf";
  pageNumber: number;
  engineLocator?: ReaderEngineLocator_Output | null;
};

export type ReaderBookSummary = {
  id: string;
  title: string;
  author?: string | null;
  coverUrl?: string | null;
};

export type ReaderBookmark_Input = {
  id: string;
  location: ReflowLocation_Input | ComicLocation_Input | PdfLocation_Input | AudioLocation_Input;
  label: string;
  percent: number;
  createdAt: string;
};

export type ReaderBookmark_Output = {
  id: string;
  location: ReflowLocation_Output | ComicLocation_Output | PdfLocation_Output | AudioLocation_Output;
  label: string;
  percent: number;
  createdAt: string;
};

export type ReaderBookmarksData = {
  bookmarks: Array<ReaderBookmark_Output>;
};

export type ReaderBookmarksReplaceRequest = {
  contentFingerprint: string;
  bookmarks: Array<ReaderBookmark_Input>;
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
  contentFingerprint: string;
  book: ReaderBookSummary;
  mediaVersion: ReaderMediaVersionSummary;
  volume: ReaderVolumeSummary;
  availableVolumes: Array<ReaderVolumeSummary>;
  files: Array<ReaderFileSummary>;
  units: Array<ReaderUnitSummary>;
  fileUrl: string;
  capabilities: ReaderCapabilities;
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

export type ReaderContentFingerprint = {
  originalFileHash: string;
  parserVersion: string;
  normalizationVersion: string;
};

export type ReaderEngineLocator_Input = {
  engine: "readium" | "foliate";
  platform: "android" | "ios" | "web";
  version: string;
  payload: {
    [key: string]: ReaderJsonValue_Input;
  };
};

export type ReaderEngineLocator_Output = {
  engine: "readium" | "foliate";
  platform: "android" | "ios" | "web";
  version: string;
  payload: {
    [key: string]: ReaderJsonValue_Output;
  };
};

export type ReaderErrorBody = {
  message: string;
  code?: string | null;
  details?: {
    [key: string]: ReaderJsonValue_Output;
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

export type ReaderJsonValue_Input = string | number | number | boolean | Array<ReaderJsonValue_Input> | {
  [key: string]: ReaderJsonValue_Input;
} | null;

export type ReaderJsonValue_Output = string | number | number | boolean | Array<ReaderJsonValue_Output> | {
  [key: string]: ReaderJsonValue_Output;
} | null;

export type ReaderMediaVersionSummary = {
  id: string;
  workId: string;
  mediaKind: "EBOOK" | "COMIC" | "AUDIOBOOK";
  completed: boolean;
};

export type ReaderProgressData = {
  progress: ReaderProgressSnapshot;
};

export type ReaderProgressPut = {
  schemaVersion: 4;
  clientId: string;
  updatedAtEpochMillis: number;
  percent: number;
  location?: ReflowLocation_Input | ComicLocation_Input | PdfLocation_Input | AudioLocation_Input | null;
  contentFingerprint: string;
};

export type ReaderProgressResponse = {
  ok?: true;
  data: ReaderProgressData;
};

export type ReaderProgressSnapshot = {
  schemaVersion?: 4;
  clientId: string;
  updatedAtEpochMillis: number;
  percent: number;
  location?: ReflowLocation_Output | ComicLocation_Output | PdfLocation_Output | AudioLocation_Output | null;
  contentFingerprint: string;
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

export type ReaderTextQuote = {
  exact: string;
  prefix?: string | null;
  suffix?: string | null;
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
    [key: string]: ReaderJsonValue_Output;
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

export type ReflowLocation_Input = {
  kind: "reflow";
  resourceKey?: string | null;
  progression?: number | null;
  position?: number | null;
  textQuote?: ReaderTextQuote | null;
  contentFingerprint?: ReaderContentFingerprint | null;
  engineLocator?: ReaderEngineLocator_Input | null;
};

export type ReflowLocation_Output = {
  kind: "reflow";
  resourceKey?: string | null;
  progression?: number | null;
  position?: number | null;
  textQuote?: ReaderTextQuote | null;
  contentFingerprint?: ReaderContentFingerprint | null;
  engineLocator?: ReaderEngineLocator_Output | null;
};
