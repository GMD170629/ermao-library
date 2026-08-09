// AUTO-GENERATED from the live FastAPI Mobile library contract.
// Run `node scripts/generate-library-api.mjs OPENAPI.json generated/library.ts`; do not edit by hand.

export type CodedMessageBody = {
  message: string;
  code: string;
};

export type ContinueReadingItem = {
  workId: string;
  title: string;
  author: string;
  coverUrl: string;
  mediaKind: "EBOOK" | "COMIC" | "AUDIOBOOK";
  volumeFormat: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  resumeVolumeId: string | null;
  progress: number;
  chapter: string | null;
  lastReadAt: string | null;
  volumeTitle: string | null;
  narrator: string | null;
};

export type ContinueReadingPayload = {
  item: ContinueReadingItem | null;
};

export type DashboardSummaryPayload = {
  totalBooks: number;
  ebookBooks: number;
  comicBooks: number;
  audiobookBooks: number;
  storageUsedBytes: number;
  monitorFolderCount: number;
  lastImportAt: string | null;
  latestSyncAt: string | null;
};

export type DeletedShelfPayload = {
  deleted: boolean;
  id: string;
};

export type ErrorEnvelope_CodedMessageBody_ = {
  ok?: false;
  error: CodedMessageBody;
};

export type ErrorEnvelope_ImportErrorBody_ = {
  ok?: false;
  error: ImportErrorBody;
};

export type ErrorEnvelope_LibraryErrorBody_ = {
  ok?: false;
  error: LibraryErrorBody;
};

export type ErrorEnvelope_RequestValidationErrorBody_ = {
  ok?: false;
  error: RequestValidationErrorBody;
};

export type ErrorEnvelope_UnsupportedPreferenceBody_ = {
  ok?: false;
  error: UnsupportedPreferenceBody;
};

export type ImportDeleteFailure = {
  path: string;
  message: string;
};

export type ImportDeletionFailureDetails = {
  failedFileDeletes: ImportDeleteFailure[];
};

export type ImportErrorBody = {
  message: string;
  code?: string | null;
  details?: ImportFileListDetails | ImportDeletionFailureDetails | null;
};

export type ImportFileListDetails = {
  files: string[];
};

export type ImportUploadPayload = {
  results: SavedUploadResult[];
  saved: number;
  autoImport: boolean;
};

export type LibraryErrorBody = {
  message: string;
  code?: string | null;
};

export type LibraryFile = {
  id: string;
  volumeId: string;
  path: string;
  mimeType: string;
  kind: string;
  sortOrder: number;
  sizeBytes: number;
  size: string;
  durationMs?: number | null;
  codec?: string | null;
  bitrate?: number | null;
  sampleRate?: number | null;
  channels?: number | null;
  discNumber?: number | null;
  trackNumber?: number | null;
  url?: string | null;
};

export type LibraryMediaVersion = {
  id: string;
  mediaKind: "EBOOK" | "COMIC" | "AUDIOBOOK";
  completed: boolean;
  volumeCount: number;
  sizeBytes: number;
  volumes: LibraryVolume[];
};

export type LibraryVolume = {
  id: string;
  mediaVersionId: string;
  title: string;
  volumeIndex?: number | null;
  sortOrder: number;
  format: string;
  readerType: "reflowable" | "comic" | "pdf" | "audio";
  classification: VolumeClassification;
  readable: boolean;
  conversionAvailable: boolean;
  kindleSendAvailable: boolean;
  derivedFromVolumeId?: string | null;
  publisher?: string | null;
  publishedAt?: string | null;
  language?: string | null;
  isbn?: string | null;
  identifier?: string | null;
  narrator?: string | null;
  abridged?: boolean | null;
  origin: string;
  importStatus: string;
  importError?: string | null;
  coverStatus: string;
  pageCount?: number | null;
  chapterCount?: number | null;
  trackCount?: number | null;
  sizeBytes: number;
  coverUrl: string;
  progress?: number;
  completed: boolean;
  lastReadAt?: string | null;
  durationMs?: number | null;
  files: LibraryFile[];
};

export type ManagementListWorkSummary = {
  id: string;
  title: string;
  author: string;
  gradient: string;
  coverStatus: string;
  coverUrl: string;
  seriesName: string | null;
  tags: string[];
  availableMediaKinds: ("EBOOK" | "COMIC" | "AUDIOBOOK")[];
  statusValue: "UNREAD" | "READING" | "FINISHED";
  lastReadAt: string | null;
  importedAt: string | null;
};

export type MediaKind = "EBOOK" | "COMIC" | "AUDIOBOOK";

export type MonitorFolder = {
  id: string;
  name: string;
  rootPath: string;
  shelfId?: string | null;
  enabled: boolean;
  mediaKindPolicy: "MIXED" | "EBOOK" | "COMIC" | "AUDIOBOOK";
  ignorePatterns?: string | null;
  ignoreHidden: boolean;
  minFileSizeBytes: number;
  description: string | null;
  createdAt: string;
  updatedAt: string;
};

export type MonitorFoldersPayload = {
  folders: MonitorFolder[];
  monitorRoot: string | null;
  lastUploadTargetPath: string | null;
  lastDownloadTargetPath: string | null;
};

export type PreferencesPayload = {
  preferences: UserPreferences;
};

export type RequestValidationErrorBody = {
  code?: "REQUEST_VALIDATION_ERROR";
  message: string;
  details: RequestValidationIssue[];
};

export type RequestValidationIssue = {
  loc: (string | number)[];
  message: string;
  type: string;
  input: ValidationInputSummary;
};

export type SavedUploadResult = {
  sourcePath: string;
  file: string;
  sizeBytes: number;
  monitoringStatus: "WATCHING" | "NOT_MONITORED";
};

export type ShelfBook = {
  id: string;
  title: string;
  author: string;
  coverUrl: string;
  availableMediaKinds: MediaKind[];
};

export type ShelfCondition = {
  field: string;
  operator: string;
  value?: string | number | number | boolean | string[] | null;
};

export type ShelfMemberView = {
  id: string;
  name: string;
  description: string | null;
  kind: "STATIC" | "SMART";
  pinned: boolean;
  bookCount: number;
  books: ShelfBook[];
  collectionIds: string[];
  createdAt: string;
  updatedAt: string;
};

export type ShelfPayload = {
  shelf: ShelfView;
};

export type ShelfRules = {
  search?: string | null;
  statuses?: string[] | null;
  mediaKinds?: string[] | null;
  tags?: string[] | null;
  authors?: string[] | null;
  publishers?: string[] | null;
  combinator?: "ALL" | "ANY" | null;
  conditions?: ShelfCondition[] | null;
  includedWorkIds?: string[] | null;
};

export type ShelfView = {
  id: string;
  ownerUserId?: string | null;
  name: string;
  description: string | null;
  kind: "STATIC" | "SMART" | "COLLECTION";
  rulesJson: string;
  pinned: boolean;
  createdAt: string;
  updatedAt: string;
  rules: ShelfRules;
  rulesStatus: "VALID" | "UNSUPPORTED";
  unsupportedRuleFields: string[];
  bookCount?: number | null;
  books?: ShelfBook[] | null;
  collectionIds?: string[] | null;
  shelfCount?: number | null;
  shelves?: ShelfMemberView[] | null;
  memberShelfIds?: string[] | null;
  page?: number | null;
  pageSize?: number | null;
  total?: number | null;
  totalPages?: number | null;
  bookIds?: string[] | null;
};

export type ShelvesPayload = {
  shelves: ShelfView[];
};

export type SuccessEnvelope_ContinueReadingPayload_ = {
  ok?: true;
  data: ContinueReadingPayload;
};

export type SuccessEnvelope_DashboardSummaryPayload_ = {
  ok?: true;
  data: DashboardSummaryPayload;
};

export type SuccessEnvelope_DeletedShelfPayload_ = {
  ok?: true;
  data: DeletedShelfPayload;
};

export type SuccessEnvelope_ImportUploadPayload_ = {
  ok?: true;
  data: ImportUploadPayload;
};

export type SuccessEnvelope_MonitorFoldersPayload_ = {
  ok?: true;
  data: MonitorFoldersPayload;
};

export type SuccessEnvelope_PreferencesPayload_ = {
  ok?: true;
  data: PreferencesPayload;
};

export type SuccessEnvelope_ShelfPayload_ = {
  ok?: true;
  data: ShelfPayload;
};

export type SuccessEnvelope_ShelvesPayload_ = {
  ok?: true;
  data: ShelvesPayload;
};

export type SuccessEnvelope_WorkSummariesPayload_ = {
  ok?: true;
  data: WorkSummariesPayload;
};

export type SuccessEnvelope_WorksPayload_ = {
  ok?: true;
  data: WorksPayload;
};

export type UnsupportedPreferenceBody = {
  message: string;
  code?: "UNSUPPORTED_USER_PREFERENCE";
  details: UnsupportedPreferenceDetails;
};

export type UnsupportedPreferenceDetails = {
  keys: string[];
};

export type UpdateUserPreferencesRequest = {
  preferences: {
    [key: string]: unknown;
  };
};

export type UserPreferences = {
  locale: "zh-CN" | "en-US";
  "library.view"?: "grid" | "list" | null;
  "library.sort"?: "recent_read" | "recent_import" | "title" | "author" | "publisher" | "series" | null;
  "library.sortDirection"?: "asc" | "desc" | null;
  "audio.playbackRate"?: number | null;
  "kindle.email"?: string | "" | null;
};

export type ValidationInputSummary = {
  kind: "null" | "boolean" | "integer" | "number" | "string" | "array" | "object";
  value?: string | number | number | boolean | null;
  length?: number | null;
  keys?: string[] | null;
};

export type VolumeClassification = {
  source: "AUTO" | "MONITOR_FOLDER" | "USER" | "INHERITED" | "LEGACY";
  reason: string;
  suggestedMediaKind?: "EBOOK" | "COMIC" | "AUDIOBOOK" | null;
};

export type WorkDetailTab = {
  key: "EBOOK" | "COMIC" | "AUDIOBOOK" | "STRUCTURE";
  label: string;
  sortOrder: number;
};

export type WorkSearchSummary = {
  id: string;
  title: string;
  author: string;
  coverUrl: string;
  availableMediaKinds: ("EBOOK" | "COMIC" | "AUDIOBOOK")[];
};

export type WorkSummariesPayload = {
  books: WorkSummary[];
};

export type WorkSummary = {
  id: string;
  title: string;
  author: string;
  coverUrl: string;
  availableMediaKinds: ("EBOOK" | "COMIC" | "AUDIOBOOK")[];
};

export type WorkView = {
  id: string;
  title: string;
  author: string;
  description?: string | null;
  publicationStatus: string;
  trackingStatus: string;
  tags: string[];
  seriesName?: string | null;
  seriesIndex?: number | null;
  organized: boolean;
  organizeStatus: string;
  metadataQuality: number;
  metadataLookupStatus?: string | null;
  metadataLookupSource?: string | null;
  metadataLookupError?: string | null;
  coverStatus: string;
  coverUrl: string;
  recentMediaKind: "EBOOK" | "COMIC" | "AUDIOBOOK" | null;
  continueVolumeId: string | null;
  continueVolumeTitle: string | null;
  continueVolumeProgress: number;
  completed: boolean;
  lastReadAt: string | null;
  addedAt: string | null;
  mediaVersions: LibraryMediaVersion[];
  availableMediaKinds: ("EBOOK" | "COMIC" | "AUDIOBOOK")[];
  detailTabs: WorkDetailTab[];
  selectedDetailTab: "EBOOK" | "COMIC" | "AUDIOBOOK" | "STRUCTURE";
};

export type WorksPayload = {
  books: (WorkView | WorkSummary | WorkSearchSummary | ManagementListWorkSummary)[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
};
