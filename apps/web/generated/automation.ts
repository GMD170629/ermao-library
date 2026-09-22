/* eslint-disable */
// AUTO-GENERATED from the automation FastAPI OpenAPI contract.
// Run pnpm --filter @shuku/web generate:automation-api; do not edit by hand.

export type CreateGrantRequest = {
  scopes?: Array<Scope>;
  libraryIds?: Array<string>;
  libraryScope?: "all" | "selected";
  name: string;
  lifetimeDays?: 30 | 90 | 365 | null;
};

export type CreatedGrantPayload = {
  grant: GrantView;
  token: string;
};

export type GrantListPayload = {
  grants: Array<GrantView>;
};

export type GrantView = {
  scopes?: Array<Scope>;
  libraryIds?: Array<string>;
  libraryScope?: "all" | "selected";
  id: string;
  tokenAvailable: boolean;
  name: string;
  createdAtMs: number;
  expiresAtMs: number | null;
  revokedAtMs: number | null;
  lastUsedAtMs: number | null;
};

export type ManagedOperationFields = {
  operation_id: string;
  grant_id: string;
  kind: string;
  created_at_ms: number;
  status: string;
  cancel_requested: boolean;
  total_targets: number;
  targets: Array<OperationTargetFields>;
  received_bytes?: number | null;
  size_bytes?: number | null;
  upload_result?: UploadOutcomeFields | null;
  file_saved?: boolean | null;
};

export type OperationListPayload = {
  operations: Array<ManagedOperationFields>;
};

export type OperationPayload = {
  operation: ManagedOperationFields;
};

export type OperationTargetFields = {
  stage: string;
  relative_path: string;
  destination_relative_path: string | null;
  error_code: string | null;
};

export type RevealedTokenPayload = {
  token: string;
};

export type RevokedGrantPayload = {
  revoked?: true;
};

export type Scope = "system:read" | "system:manage" | "books:write" | "shelves:write" | "files:upload" | "files:modify";

export type ServiceSettingsFields = {
  enabled?: boolean;
  enabledScopes?: Array<Scope>;
  publicBaseUrl?: string;
};

export type UpdateGrantRequest = {
  scopes?: Array<Scope>;
  libraryIds?: Array<string>;
  libraryScope?: "all" | "selected";
  name: string;
  lifetimeDays?: 30 | 90 | 365 | null;
};

export type UpdatedGrantPayload = {
  grant: GrantView;
};

export type UploadOutcomeFields = {
  status: string;
  task_id?: string | null;
  book_ids?: Array<string>;
  resource_ids?: Array<string>;
  cover_url?: string | null;
  revision?: string | null;
  error_code?: string | null;
};
