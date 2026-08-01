/* eslint-disable */
// AUTO-GENERATED from the Reader v3 FastAPI OpenAPI contract.
// Run `pnpm --filter @shuku/web generate:reader-api`; do not edit by hand.

export type AudioLocation = {
  type: "audio";
  volumeId?: string | null;
  fileId: string;
  chapterId?: string | null;
  positionMs: number;
};

export type ComicLocation = {
  type: "comic";
  volumeId?: string | null;
  pageIndex: number;
};

export type EpubLocation = {
  type: "epub";
  volumeId?: string | null;
  cfi?: string | null;
  href?: string | null;
  spineIndex?: number | null;
  progression?: number | null;
};

export type PdfLocation = {
  type: "pdf";
  volumeId?: string | null;
  pageNumber: number;
};

export type ReaderBookSummary = {
  id: string;
  title: string;
  author?: string | null;
  coverUrl?: string | null;
};

export type ReaderBookmark_Input = {
  id: string;
  location: EpubLocation | ReflowableLocation_Input | ComicLocation | PdfLocation | AudioLocation;
  label: string;
  percent: number;
  createdAt: string;
};

export type ReaderBookmark_Output = {
  id: string;
  location: EpubLocation | ReflowableLocation_Output | ComicLocation | PdfLocation | AudioLocation;
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
  schemaVersion?: 3;
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
  resumeLocation?: EpubLocation | ReflowableLocation_Output | ComicLocation | PdfLocation | AudioLocation | null;
  resumeFingerprintMismatch?: boolean;
  progressPercent?: number;
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
};

export type ReaderJsonValue_Input = {
  [key: string]: ReaderJsonValue_Input;
} | Array<ReaderJsonValue_Input> | string | number | number | boolean | null;

export type ReaderJsonValue_Output = {
  [key: string]: ReaderJsonValue_Output;
} | Array<ReaderJsonValue_Output> | string | number | number | boolean | null;

export type ReaderMediaVersionSummary = {
  id: string;
  workId: string;
  mediaKind: "EBOOK" | "COMIC" | "AUDIOBOOK";
  completed: boolean;
};

export type ReaderProgressData = {
  mutationId: string;
  applied: boolean;
  progress: ReaderProgressRecord;
};

export type ReaderProgressPut = {
  schemaVersion: 3;
  mutationId: string;
  clientId: string;
  clientSequence: number;
  contentFingerprint: string;
  location: EpubLocation | ReflowableLocation_Input | ComicLocation | PdfLocation | AudioLocation;
  percent: number;
};

export type ReaderProgressRecord = {
  schemaVersion?: 3;
  mutationId: string;
  clientId: string;
  clientSequence: number;
  contentFingerprint: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  workId: string;
  volumeId: string;
  location: EpubLocation | ReflowableLocation_Output | ComicLocation | PdfLocation | AudioLocation;
  percent: number;
  updatedAt: string;
};

export type ReaderProgressResponse = {
  ok?: true;
  data: ReaderProgressData;
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

export type ReflowableLocation_Input = {
  type: "reflowable";
  volumeId?: string | null;
  format: "epub" | "mobi" | "azw" | "azw3" | "prc" | "fb2" | "txt";
  cfi?: string | null;
  href?: string | null;
  progression?: number | null;
  foliate?: {
    [key: string]: ReaderJsonValue_Input;
  } | null;
};

export type ReflowableLocation_Output = {
  type: "reflowable";
  volumeId?: string | null;
  format: "epub" | "mobi" | "azw" | "azw3" | "prc" | "fb2" | "txt";
  cfi?: string | null;
  href?: string | null;
  progression?: number | null;
  foliate?: {
    [key: string]: ReaderJsonValue_Output;
  } | null;
};
