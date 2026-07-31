/* eslint-disable */
// AUTO-GENERATED from apps/api-python/app/schemas/reader_v2.py via FastAPI OpenAPI.
// Run `pnpm --filter @shuku/web generate:reader-api`; do not edit by hand.

export type AppearancePreferences = {
  theme?: "day" | "warm" | "night" | "black";
};

export type AudioChapterSummary = {
  id: string;
  title: string;
  fileId: string;
  startMs: number;
  endMs: number;
  durationMs: number;
  sortOrder: number;
};

export type AudioLocation = {
  type: "audio";
  volumeId?: string | null;
  fileId: string;
  chapterId?: string | null;
  positionMs: number;
};

export type AudioPreferences = {
  playbackRate?: number;
  skipBackwardSeconds?: number;
  skipForwardSeconds?: number;
  volume?: number;
};

export type AudioTrackSummary = {
  fileId: string;
  title: string;
  url: string;
  mimeType: string;
  durationMs: number;
  discNumber?: number | null;
  trackNumber?: number | null;
  sortOrder: number;
};

export type ComicLocation = {
  type: "comic";
  volumeId: string;
  pageIndex: number;
};

export type ComicPreferences = {
  direction?: "ltr" | "rtl";
  mode?: "single" | "double";
  pageTurnAnimation?: "slide" | "off";
  imageFit?: "width" | "height" | "contain" | "original";
  imageVariant?: "original" | "data-saver";
  zoom?: number;
};

export type EpubLocation = {
  type: "epub";
  cfi?: string | null;
  href?: string | null;
  spineIndex?: number | null;
  progression?: number | null;
};

export type EpubPreferences = {
  fontSize?: number;
  lineHeight?: number;
  pageWidth?: number;
  fontFamily?: "pingfang" | "heiti" | "songti" | "yahei" | "kaiti";
  spreadMode?: "single" | "double";
  pageTurnAnimation?: "slide" | "off";
  flow?: "paginated" | "scrolled";
};

export type PdfLocation = {
  type: "pdf";
  pageNumber: number;
};

export type PdfPreferences = {
  zoom?: number;
  fit?: "width" | "page";
};

export type ReaderBookSummary = {
  id: string;
  title: string;
  author?: string | null;
  coverUrl?: string | null;
};

export type ReaderBookmark = {
  id: string;
  location: ReaderBookmarkLocation;
  label: string;
  percent: number;
  createdAt: string;
};

export type ReaderBookmarkLocation = {
  kind: "epub" | "reflowable" | "comic" | "pdf" | "audio";
  format?: "epub" | "mobi" | "azw" | "azw3" | "prc" | "fb2" | "txt" | null;
  cfi?: string | null;
  href?: string | null;
  spineIndex?: number | null;
  progression?: number | null;
  pageIndex?: number | null;
  pageNumber?: number | null;
  volumeId?: string | null;
  fileId?: string | null;
  chapterId?: string | null;
  positionMs?: number | null;
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
  schemaVersion?: 2;
  userId: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  sourceFormat?: "epub" | "mobi" | "azw" | "azw3" | "prc" | "fb2" | "txt" | null;
  contentFingerprint: string;
  book: ReaderBookSummary;
  edition: ReaderEditionSummary;
  availableEditions: Array<ReaderEditionOption>;
  selectedVolume?: ReaderVolumeSummary | null;
  volumes: Array<ReaderVolumeSummary>;
  units: Array<ReaderUnitSummary>;
  pages: Array<ReaderPageSummary>;
  tracks?: Array<AudioTrackSummary>;
  chapters?: Array<AudioChapterSummary>;
  totalDurationMs?: number | null;
  totalPages?: number | null;
  fileUrl: string;
  capabilities: ReaderCapabilities;
  serverPreferences: ReaderServerPreferences;
  resumeLocation?: EpubLocation | ReflowableLocation | ComicLocation | PdfLocation | AudioLocation | null;
  resumeFingerprintMismatch?: boolean;
  resumeDiscardedReason?: "content_fingerprint_mismatch" | null;
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
  readingDirection: "ltr" | "rtl";
};

export type ReaderEditionOption = {
  id: string;
  workId: string;
  format: "reflowable" | "comic" | "pdf" | "audio";
  sourceFormat?: "epub" | "mobi" | "azw" | "azw3" | "prc" | "fb2" | "txt" | null;
  versionName: string;
  pageCount?: number | null;
  chapterCount?: number | null;
  mediaKind?: "EBOOK" | "COMIC" | "AUDIOBOOK" | null;
  durationMs?: number | null;
  trackCount?: number | null;
  narrator?: string | null;
  progress: number;
  lastReadAt: string | null;
  volumes: Array<ReaderVolumeSummary>;
};

export type ReaderEditionSummary = {
  id: string;
  workId: string;
  format: "reflowable" | "comic" | "pdf" | "audio";
  sourceFormat?: "epub" | "mobi" | "azw" | "azw3" | "prc" | "fb2" | "txt" | null;
  versionName: string;
  pageCount?: number | null;
  chapterCount?: number | null;
  mediaKind?: "EBOOK" | "COMIC" | "AUDIOBOOK" | null;
  durationMs?: number | null;
  trackCount?: number | null;
  narrator?: string | null;
};

export type ReaderErrorBody = {
  message: string;
  code?: string | null;
  details?: ReaderErrorDetails | null;
};

export type ReaderErrorDetails = {
  expectedContentFingerprint: string;
  receivedContentFingerprint: string;
  editionId: string;
  volumeId: string | null;
};

export type ReaderPageSummary = {
  pageIndex: number;
  title?: string | null;
  mimeType?: string | null;
  width?: number | null;
  height?: number | null;
  size?: number | null;
};

export type ReaderPreferences = {
  schemaVersion?: 3;
  appearance?: AppearancePreferences;
  epub?: EpubPreferences;
  comic?: ComicPreferences;
  pdf?: PdfPreferences;
  audio?: AudioPreferences;
};

export type ReaderProgressData = {
  mutationId: string;
  applied: boolean;
  progress: ReaderProgressRecord;
};

export type ReaderProgressPut = {
  schemaVersion: 2;
  userId: string;
  mutationId: string;
  clientId: string;
  clientSequence: number;
  contentFingerprint: string;
  volumeId?: string | null;
  location: EpubLocation | ReflowableLocation | ComicLocation | PdfLocation | AudioLocation;
  percent: number;
};

export type ReaderProgressRecord = {
  schemaVersion?: 2;
  mutationId: string;
  clientId: string;
  clientSequence: number;
  contentFingerprint: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  workId: string;
  editionId: string;
  volumeId?: string | null;
  location: EpubLocation | ReflowableLocation | ComicLocation | PdfLocation | AudioLocation;
  percent: number;
  updatedAt: string;
};

export type ReaderProgressResponse = {
  ok?: true;
  data: ReaderProgressData;
};

export type ReaderRetiredBody = {
  message?: "READER_V1_RETIRED";
  details: ReaderRetiredDetails;
};

export type ReaderRetiredDetails = {
  replacement: string;
};

export type ReaderServerPreferences = {
  schemaVersion?: 3;
  settings: ReaderPreferences;
  updatedAt?: string | null;
};

export type ReaderUnitSummary = {
  id?: string | null;
  index: number;
  title: string;
  href?: string | null;
  fileId?: string | null;
  startMs?: number | null;
  endMs?: number | null;
  durationMs?: number | null;
};

export type ReaderVolumeSummary = {
  id: string;
  title: string;
  index: number;
  pageCount?: number | null;
  chapterCount?: number | null;
  durationMs?: number | null;
};

export type ReflowableLocation = {
  type: "reflowable";
  format: "epub" | "mobi" | "azw" | "azw3" | "prc" | "fb2" | "txt";
  cfi?: string | null;
  href?: string | null;
  progression?: number | null;
};
