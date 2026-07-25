/* eslint-disable */
// AUTO-GENERATED from appv2 FastAPI OpenAPI. Do not edit by hand.
// Run `pnpm --filter @shuku/web generate:api-v2`.

export type AccessScope = "catalog:read" | "catalog:write" | "ingestion:write" | "metadata:write" | "reading:write" | "discovery:write" | "delivery:write" | "operations:read" | "operations:write" | "users:write";

export type AccountPreferences = {
  values: {
    [key: string]: unknown;
  };
};

export type AccountResponse = {
  id: string;
  email: string;
  displayName: string;
  role: string;
  locale: string;
  scopes: Array<string>;
  disabled: boolean;
  monitorFolderIds: Array<string>;
  createdAt: string;
};

export type AdminPasswordRequest = {
  password: string;
};

export type AdminUpdateUserRequest = {
  email?: string | null;
  displayName?: string | null;
  role?: "admin" | "member" | null;
  disabled?: boolean | null;
  locale?: "zh-CN" | "en-US" | null;
  scopes?: Array<AccessScope> | null;
  monitorFolderIds?: Array<string> | null;
};

export type BackupResponse = {
  id: string;
  status: string;
  archiveName: string;
  appVersion: string;
  postgresMajor: number;
  alembicRevision: string;
  checksum: string | null;
  sizeBytes: number | null;
  errorDetail: string | null;
  createdAt: string;
  updatedAt: string;
};

export type Body_upload_api_v2_ingestion_imports_upload_post = {
  file: string;
};

export type BookmarkRequest = {
  clientId: string;
  label?: string | null;
  position: {
    [key: string]: unknown;
  };
  excerpt?: string | null;
};

export type BookmarkResponse = {
  id: string;
  editionId: string;
  clientId: string;
  label: string | null;
  position: {
    [key: string]: unknown;
  };
  excerpt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type BootstrapResponse = {
  accountId: string;
  target: ReaderTargetResponse;
  progress: ProgressResponse | null;
  bookmarks: Array<BookmarkResponse>;
  preference: PreferenceResponse | null;
};

export type CandidateResponse = {
  providerId: string;
  externalId: string;
  title: string;
  author: string | null;
  confidence: number;
  coverUrl: string | null;
  rawPayload: {
    [key: string]: unknown;
  };
};

export type CategoryMergeRequest = {
  kind: string;
  targetId: string;
  sourceIds: Array<string>;
};

export type CategoryResponse = {
  id: string;
  kind: string;
  name: string;
  aliases?: Array<string>;
  bookCount: number;
};

export type CategoryUpdateRequest = {
  name: string;
};

export type ComicPageIndexResponse = {
  pageCount: number;
  pages: Array<ComicPageResponse>;
};

export type ComicPageResponse = {
  pageIndex: number;
  title: string;
  mimeType: string;
  size: number;
};

export type CreateUserRequest = {
  email: string;
  displayName: string;
  password: string;
  locale?: "zh-CN" | "en-US";
  role?: "admin" | "member";
  scopes?: Array<AccessScope> | null;
  monitorFolderIds?: Array<string>;
};

export type CreateWorkRequest = {
  title: string;
  author?: string | null;
  mediaType: "book" | "comic" | "pdf" | "audiobook" | "text";
  metadata?: {
    [key: string]: unknown;
  };
};

export type DashboardResponse = {
  workCount: number;
  editionCount: number;
  activeReaders: number;
  queuedJobs: number;
  recentItems: Array<{
      [key: string]: unknown;
    }>;
};

export type DeletedJobsResponse = {
  deleted: number;
};

export type DeliveryJobResponse = {
  id: string;
  fileId: string;
  kind: string;
  recipient: string;
  subject: string;
  status: string;
  attempt: number;
  nextAttemptAt: string;
  errorCode: string | null;
  createdAt: string;
  updatedAt: string;
};

export type DirectoryNodeResponse = {
  name: string;
  path: string;
  readable: boolean;
  error: string | null;
  children: Array<DirectoryNodeResponse>;
};

export type DirectoryTreeResponse = {
  node: DirectoryNodeResponse;
  monitorRoot: string;
};

export type DownloadResponse = {
  id: string;
  resultId: string;
  status: string;
  attempt: number;
  nextAttemptAt: string;
  destinationPath: string | null;
  errorCode: string | null;
  createdAt: string;
  updatedAt: string;
};

export type EditionResponse = {
  id: string;
  workId: string;
  title: string;
  format: string;
  language: string | null;
  primary: boolean;
  createdAt: string;
};

export type EmailSettingsRequest = {
  host: string;
  port: number;
  username?: string | null;
  password?: string | null;
  sender: string;
  useTls?: boolean;
};

export type EmailSettingsResponse = {
  ownerId: string;
  host: string;
  port: number;
  username: string | null;
  sender: string;
  useTls: boolean;
  passwordSet: boolean;
};

export type EmailTestRequest = {
  recipient: string;
};

export type EnqueueRequest = {
  sourcePath: string;
  moveSource?: boolean;
};

export type EpubLocationClaimRequest = {
  cacheVersion: number;
  contentFingerprint: string;
  breakSize: number;
};

export type EpubLocationClaimResponse = {
  status: "ready" | "claimed" | "generating";
  serialized?: string | null;
  leaseToken?: string | null;
  leaseExpiresAt?: number | null;
  retryAfterMs?: number | null;
};

export type EpubLocationSaveRequest = {
  cacheVersion: number;
  contentFingerprint: string;
  breakSize: number;
  leaseToken: string;
  serialized: string;
};

export type EventResponse = {
  id: string;
  actorId: string | null;
  kind: string;
  severity: string;
  messageKey: string;
  params: {
    [key: string]: unknown;
  };
  traceId: string | null;
  createdAt: string;
};

export type FacetsResponse = {
  facets: {
    [key: string]: Array<{
        [key: string]: unknown;
      }>;
  };
};

export type FolderRequest = {
  path: string;
  recursive?: boolean;
  moveSource?: boolean;
  options?: {
    [key: string]: unknown;
  };
};

export type FolderResponse = {
  id: string;
  path: string;
  enabled: boolean;
  recursive: boolean;
  moveSource: boolean;
  options: {
    [key: string]: unknown;
  };
  lastScanAt: string | null;
  createdAt: string;
};

export type FolderUpdate = {
  enabled?: boolean | null;
  recursive?: boolean | null;
  moveSource?: boolean | null;
  options?: {
    [key: string]: unknown;
  } | null;
};

export type HealthItem = {
  name: string;
  status: string;
  checkedAt: string;
  detail: {
    [key: string]: unknown;
  };
};

export type HealthResponse = {
  status: string;
  version: string;
  contributors: Array<HealthItem>;
};

export type JobAccepted = {
  id: string;
  status: string;
  duplicate: boolean;
  resultId: string | null;
};

export type JobResponse = {
  id: string;
  kind: string;
  status: string;
  sourcePath: string;
  attempt: number;
  nextAttemptAt: string;
  leaseExpiresAt: string | null;
  resultId: string | null;
  errorCode: string | null;
  createdAt: string;
  updatedAt: string;
};

export type KindleJobRequest = {
  fileId: string;
  subject: string;
};

export type KindleSettingsRequest = {
  kindleEmail: string;
  convertBeforeSend?: boolean;
  options?: {
    [key: string]: unknown;
  };
};

export type KindleSettingsResponse = {
  ownerId: string;
  kindleEmail: string;
  convertBeforeSend: boolean;
  options: {
    [key: string]: unknown;
  };
};

export type LoginRequest = {
  email: string;
  password: string;
};

export type ManagementResponse = {
  users: number;
  works: number;
  files: number;
  queuedImports: number;
  queuedDownloads: number;
  queuedDeliveries: number;
  failedJobs: number;
};

export type MetadataJobRequest = {
  workId: string;
  query: string;
};

export type MetadataJobResponse = {
  id: string;
  workId: string;
  status: string;
  query: string;
  attempt: number;
  nextAttemptAt: string;
  leaseExpiresAt: string | null;
  errorCode: string | null;
  createdAt: string;
  updatedAt: string;
};

export type Page_AccountResponse_ = {
  items: Array<AccountResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_BackupResponse_ = {
  items: Array<BackupResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_BookmarkResponse_ = {
  items: Array<BookmarkResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_CandidateResponse_ = {
  items: Array<CandidateResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_CategoryResponse_ = {
  items: Array<CategoryResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_DeliveryJobResponse_ = {
  items: Array<DeliveryJobResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_DownloadResponse_ = {
  items: Array<DownloadResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_EventResponse_ = {
  items: Array<EventResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_FolderResponse_ = {
  items: Array<FolderResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_JobAccepted_ = {
  items: Array<JobAccepted>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_JobResponse_ = {
  items: Array<JobResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_MetadataJobResponse_ = {
  items: Array<MetadataJobResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_ProviderResponse_ = {
  items: Array<ProviderResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_ResultResponse_ = {
  items: Array<ResultResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_ShelfResponse_ = {
  items: Array<ShelfResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_SourceResponse_ = {
  items: Array<SourceResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type Page_WorkResponse_ = {
  items: Array<WorkResponse>;
  page: number;
  pageSize: number;
  total: number;
};

export type PasswordResetAccepted = {
  accepted?: boolean;
  message: string;
  filePath: string;
};

export type PasswordResetCompleted = {
  passwordReset?: boolean;
};

export type PasswordResetConfirmRequest = {
  token: string;
  newPassword: string;
};

export type PasswordResetRequest = {
  email: string;
};

export type PreferenceRequest = {
  scope: string;
  targetId?: string | null;
  values: {
    [key: string]: unknown;
  };
};

export type PreferenceResponse = {
  scope: string;
  targetId: string | null;
  values: {
    [key: string]: unknown;
  };
  updatedAt: string;
};

export type ProblemDetails = {
  type: string;
  title: string;
  status: number;
  code: string;
  detail: string;
  params?: {
    [key: string]: unknown;
  };
  traceId: string;
};

export type ProgressRequest = {
  deviceId: string;
  position: {
    [key: string]: unknown;
  };
  percentage: number;
  occurredAt?: string | null;
  expectedVersion?: number | null;
};

export type ProgressResponse = {
  editionId: string;
  position: {
    [key: string]: unknown;
  };
  percentage: number;
  version: number;
  updatedAt: string;
};

export type ProviderRequest = {
  slug: string;
  name: string;
  enabled?: boolean;
  priority?: number;
  config?: {
    [key: string]: unknown;
  };
};

export type ProviderResponse = {
  id: string;
  slug: string;
  name: string;
  enabled: boolean;
  priority: number;
  config: {
    [key: string]: unknown;
  };
  createdAt: string;
  updatedAt: string;
};

export type ProviderUpdate = {
  name?: string | null;
  enabled?: boolean | null;
  priority?: number | null;
  config?: {
    [key: string]: unknown;
  } | null;
};

export type ReaderTargetResponse = {
  workId: string;
  workTitle: string;
  workAuthor: string | null;
  editionId: string;
  editionTitle: string;
  fileId: string;
  format: string;
  mediaType: string;
  resourceUrl: string;
  checksum: string;
};

export type RestoreAccepted = {
  requestId: string;
  status?: string;
};

export type ResultResponse = {
  id: string;
  sourceId: string;
  externalId: string;
  title: string;
  author: string | null;
  downloadUrl: string | null;
  infoUrl: string | null;
  payload: {
    [key: string]: unknown;
  };
  state: string;
  createdAt: string;
};

export type ScanDirectoryRequest = {
  path: string;
};

export type ScanDirectoryResponse = {
  path: string;
  directoriesScanned: number;
  filesScanned: number;
  candidatesFound: number;
  queued: number;
  skipped: number;
  errors: Array<{
      [key: string]: string;
    }>;
};

export type SearchRequest = {
  query: string;
};

export type SessionResponse = {
  account: AccountResponse;
  expiresAt: string;
};

export type SettingsRequest = {
  values?: {
    [key: string]: {
      [key: string]: unknown;
    };
  };
};

export type SettingsResponse = {
  values: {
    [key: string]: {
      [key: string]: unknown;
    };
  };
  updatedAt: {
    [key: string]: string;
  };
};

export type SetupRequest = {
  email: string;
  displayName: string;
  password: string;
  locale?: "zh-CN" | "en-US";
};

export type SetupStatusResponse = {
  required: boolean;
};

export type ShelfDetailResponse = {
  id: string;
  ownerId: string;
  name: string;
  description: string | null;
  kind: string;
  rules: {
    [key: string]: unknown;
  };
  pinned: boolean;
  createdAt: string;
  bookCount: number;
  bookIds: Array<string>;
  books: Array<WorkResponse>;
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
};

export type ShelfRequest = {
  name: string;
  description?: string | null;
  kind?: "manual" | "smart";
  rules?: {
    [key: string]: unknown;
  };
  pinned?: boolean;
  bookIds?: Array<string>;
};

export type ShelfResponse = {
  id: string;
  ownerId: string;
  name: string;
  description: string | null;
  kind: string;
  rules: {
    [key: string]: unknown;
  };
  pinned: boolean;
  createdAt: string;
};

export type ShelfUpdateRequest = {
  name?: string | null;
  description?: string | null;
  rules?: {
    [key: string]: unknown;
  } | null;
  pinned?: boolean | null;
  bookIds?: Array<string> | null;
};

export type SourceRequest = {
  name: string;
  kind?: "json-http";
  baseUrl: string;
  enabled?: boolean;
  config?: {
    [key: string]: unknown;
  };
};

export type SourceResponse = {
  id: string;
  name: string;
  kind: string;
  baseUrl: string;
  enabled: boolean;
  config: {
    [key: string]: unknown;
  };
  createdAt: string;
  updatedAt: string;
};

export type SourceUpdate = {
  name?: string | null;
  baseUrl?: string | null;
  enabled?: boolean | null;
  config?: {
    [key: string]: unknown;
  } | null;
};

export type UpdateAccountPreferences = {
  values: {
    [key: string]: unknown;
  };
};

export type UpdateAccountRequest = {
  email?: string | null;
  displayName?: string | null;
  password?: string | null;
  currentPassword?: string | null;
  locale?: "zh-CN" | "en-US" | null;
};

export type UpdateWorkRequest = {
  title?: string | null;
  author?: string | null;
  summary?: string | null;
  status?: "active" | "archived" | null;
};

export type WorkDetailResponse = {
  id: string;
  title: string;
  author: string | null;
  mediaType: string;
  status: string;
  coverUrl: string | null;
  createdAt: string;
  updatedAt: string;
  editions: Array<EditionResponse>;
};

export type WorkResponse = {
  id: string;
  title: string;
  author: string | null;
  mediaType: string;
  status: string;
  coverUrl: string | null;
  createdAt: string;
  updatedAt: string;
};

export interface ApiV2Paths {
  "/api/v2/auth/setup/status": {
    get: { request: never; query: never; response: SetupStatusResponse };
  };
  "/api/v2/auth/setup": {
    post: { request: SetupRequest; query: never; response: SessionResponse };
  };
  "/api/v2/auth/login": {
    post: { request: LoginRequest; query: never; response: SessionResponse };
  };
  "/api/v2/auth/logout": {
    post: { request: never; query: never; response: void };
  };
  "/api/v2/auth/password-reset/request": {
    post: { request: PasswordResetRequest; query: never; response: PasswordResetAccepted };
  };
  "/api/v2/auth/password-reset/confirm": {
    post: { request: PasswordResetConfirmRequest; query: never; response: PasswordResetCompleted };
  };
  "/api/v2/account": {
    get: { request: never; query: never; response: AccountResponse };
    patch: { request: UpdateAccountRequest; query: never; response: AccountResponse };
  };
  "/api/v2/account/preferences": {
    get: { request: never; query: never; response: AccountPreferences };
    patch: { request: UpdateAccountPreferences; query: never; response: AccountPreferences };
  };
  "/api/v2/admin/users": {
    get: { request: never; query: { page?: number; pageSize?: number }; response: Page_AccountResponse_ };
    post: { request: CreateUserRequest; query: never; response: AccountResponse };
  };
  "/api/v2/admin/users/{user_id}": {
    patch: { request: AdminUpdateUserRequest; query: never; response: AccountResponse };
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/admin/users/{user_id}/password": {
    put: { request: AdminPasswordRequest; query: never; response: void };
  };
  "/api/v2/catalog/works": {
    get: { request: never; query: { page?: number; pageSize?: number; query?: string | null; mediaType?: string | null; visibility?: string }; response: Page_WorkResponse_ };
    post: { request: CreateWorkRequest; query: never; response: WorkResponse };
  };
  "/api/v2/catalog/works/{work_id}": {
    get: { request: never; query: never; response: WorkDetailResponse };
    patch: { request: UpdateWorkRequest; query: never; response: WorkResponse };
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/catalog/shelves": {
    get: { request: never; query: never; response: Page_ShelfResponse_ };
    post: { request: ShelfRequest; query: never; response: ShelfResponse };
  };
  "/api/v2/catalog/shelves/{shelf_id}": {
    get: { request: never; query: { page?: number; pageSize?: number }; response: ShelfDetailResponse };
    patch: { request: ShelfUpdateRequest; query: never; response: ShelfResponse };
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/catalog/shelves/{shelf_id}/works/{work_id}": {
    put: { request: never; query: never; response: void };
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/catalog/facets": {
    get: { request: never; query: never; response: FacetsResponse };
  };
  "/api/v2/catalog/categories": {
    get: { request: never; query: { kind: string; page?: number; pageSize?: number; search?: string | null }; response: Page_CategoryResponse_ };
  };
  "/api/v2/catalog/categories/{category_id}": {
    patch: { request: CategoryUpdateRequest; query: never; response: CategoryResponse };
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/catalog/categories/merge": {
    post: { request: CategoryMergeRequest; query: never; response: CategoryResponse };
  };
  "/api/v2/ingestion/imports": {
    get: { request: never; query: { page?: number; pageSize?: number; status?: string | null }; response: Page_JobResponse_ };
    post: { request: EnqueueRequest; query: never; response: JobAccepted };
    delete: { request: never; query: never; response: DeletedJobsResponse };
  };
  "/api/v2/ingestion/imports/upload": {
    post: { request: Body_upload_api_v2_ingestion_imports_upload_post; query: never; response: JobAccepted };
  };
  "/api/v2/ingestion/imports/{job_id}/retry": {
    post: { request: never; query: never; response: JobAccepted };
  };
  "/api/v2/ingestion/imports/rescan": {
    post: { request: never; query: never; response: Page_JobAccepted_ };
  };
  "/api/v2/ingestion/imports/scan-directory": {
    post: { request: ScanDirectoryRequest; query: never; response: ScanDirectoryResponse };
  };
  "/api/v2/ingestion/imports/{job_id}": {
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/ingestion/folders": {
    get: { request: never; query: never; response: Page_FolderResponse_ };
    post: { request: FolderRequest; query: never; response: FolderResponse };
  };
  "/api/v2/ingestion/folders/tree": {
    get: { request: never; query: { path?: string | null }; response: DirectoryTreeResponse };
  };
  "/api/v2/ingestion/folders/{folder_id}": {
    patch: { request: FolderUpdate; query: never; response: FolderResponse };
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/ingestion/folders/{folder_id}/scan": {
    post: { request: never; query: never; response: Page_JobAccepted_ };
  };
  "/api/v2/ingestion/conversions": {
    get: { request: never; query: { page?: number; pageSize?: number }; response: Page_JobResponse_ };
  };
  "/api/v2/metadata/providers": {
    get: { request: never; query: never; response: Page_ProviderResponse_ };
    post: { request: ProviderRequest; query: never; response: ProviderResponse };
  };
  "/api/v2/metadata/providers/{provider_id}": {
    patch: { request: ProviderUpdate; query: never; response: ProviderResponse };
  };
  "/api/v2/metadata/jobs": {
    get: { request: never; query: { page?: number; pageSize?: number; status?: string | null }; response: Page_MetadataJobResponse_ };
    post: { request: MetadataJobRequest; query: never; response: MetadataJobResponse };
  };
  "/api/v2/metadata/jobs/{job_id}/candidates": {
    get: { request: never; query: never; response: Page_CandidateResponse_ };
  };
  "/api/v2/reading/editions/{edition_id}/bootstrap": {
    get: { request: never; query: never; response: BootstrapResponse };
  };
  "/api/v2/reading/editions/{edition_id}/resource": {
    get: { request: never; query: never; response: unknown };
  };
  "/api/v2/reading/volumes/{edition_id}/pages": {
    get: { request: never; query: never; response: ComicPageIndexResponse };
  };
  "/api/v2/reading/volumes/{edition_id}/pages/{page_index}": {
    get: { request: never; query: never; response: unknown };
  };
  "/api/v2/reading/editions/{edition_id}/epub-locations/claim": {
    post: { request: EpubLocationClaimRequest; query: never; response: EpubLocationClaimResponse };
  };
  "/api/v2/reading/editions/{edition_id}/epub-locations": {
    put: { request: EpubLocationSaveRequest; query: never; response: EpubLocationClaimResponse };
  };
  "/api/v2/reading/editions/{edition_id}/progress": {
    get: { request: never; query: never; response: ProgressResponse | null };
    put: { request: ProgressRequest; query: never; response: ProgressResponse };
  };
  "/api/v2/reading/editions/{edition_id}/bookmarks": {
    get: { request: never; query: never; response: Page_BookmarkResponse_ };
    put: { request: BookmarkRequest; query: never; response: BookmarkResponse };
  };
  "/api/v2/reading/editions/{edition_id}/bookmarks/{bookmark_id}": {
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/reading/preferences": {
    get: { request: never; query: { scope?: string; targetId?: string | null }; response: PreferenceResponse | null };
    put: { request: PreferenceRequest; query: never; response: PreferenceResponse };
  };
  "/api/v2/discovery/sources": {
    get: { request: never; query: never; response: Page_SourceResponse_ };
    post: { request: SourceRequest; query: never; response: SourceResponse };
  };
  "/api/v2/discovery/sources/{source_id}": {
    patch: { request: SourceUpdate; query: never; response: SourceResponse };
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/discovery/sources/{source_id}/search": {
    post: { request: SearchRequest; query: never; response: Page_ResultResponse_ };
  };
  "/api/v2/discovery/results": {
    get: { request: never; query: { page?: number; pageSize?: number; state?: string | null }; response: Page_ResultResponse_ };
  };
  "/api/v2/discovery/downloads/{result_id}": {
    post: { request: never; query: never; response: DownloadResponse };
  };
  "/api/v2/discovery/downloads": {
    get: { request: never; query: { page?: number; pageSize?: number; status?: string | null }; response: Page_DownloadResponse_ };
  };
  "/api/v2/delivery/email/settings": {
    get: { request: never; query: never; response: EmailSettingsResponse | null };
    put: { request: EmailSettingsRequest; query: never; response: EmailSettingsResponse };
  };
  "/api/v2/delivery/email/test": {
    post: { request: EmailTestRequest; query: never; response: void };
  };
  "/api/v2/delivery/kindle/settings": {
    get: { request: never; query: never; response: KindleSettingsResponse | null };
    put: { request: KindleSettingsRequest; query: never; response: KindleSettingsResponse };
  };
  "/api/v2/delivery/kindle/jobs": {
    post: { request: KindleJobRequest; query: never; response: DeliveryJobResponse };
    get: { request: never; query: { page?: number; pageSize?: number; status?: string | null }; response: Page_DeliveryJobResponse_ };
  };
  "/api/v2/delivery/kindle/jobs/{job_id}/retry": {
    post: { request: never; query: never; response: DeliveryJobResponse | null };
  };
  "/api/v2/delivery/kindle/jobs/{job_id}": {
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/operations/health": {
    get: { request: never; query: never; response: HealthResponse };
  };
  "/api/v2/operations/settings": {
    get: { request: never; query: never; response: SettingsResponse };
    put: { request: SettingsRequest; query: never; response: SettingsResponse };
  };
  "/api/v2/operations/events": {
    get: { request: never; query: { page?: number; pageSize?: number; kind?: string | null }; response: Page_EventResponse_ };
  };
  "/api/v2/operations/backups": {
    get: { request: never; query: never; response: Page_BackupResponse_ };
    post: { request: never; query: never; response: BackupResponse };
  };
  "/api/v2/operations/backups/{backup_id}": {
    get: { request: never; query: never; response: BackupResponse };
    delete: { request: never; query: never; response: void };
  };
  "/api/v2/operations/backups/{backup_id}/download": {
    get: { request: never; query: never; response: unknown };
  };
  "/api/v2/operations/backups/{backup_id}/restore": {
    post: { request: never; query: never; response: RestoreAccepted };
  };
  "/api/v2/reporting/dashboard": {
    get: { request: never; query: never; response: DashboardResponse };
  };
  "/api/v2/reporting/management": {
    get: { request: never; query: never; response: ManagementResponse };
  };
}
