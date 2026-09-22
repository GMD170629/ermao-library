/* eslint-disable */
// AUTO-GENERATED from the automation FastAPI OpenAPI contract.
// Run pnpm --filter @shuku/web generate:automation-api; do not edit by hand.

export type CreateGrantRequest = {
  scopes?: Array<Scope>;
  libraryIds?: Array<string>;
  libraryScope?: "all" | "selected";
  writebackTargets?: Array<WritebackTarget>;
  allowCrossLibrary?: boolean;
  name: string;
  lifetimeDays?: 30 | 90 | 365;
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
  writebackTargets?: Array<WritebackTarget>;
  allowCrossLibrary?: boolean;
  id: string;
  tokenAvailable: boolean;
  name: string;
  createdAtMs: number;
  expiresAtMs: number;
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

export type Scope = "library:read" | "shelves:write" | "tags:write" | "files:read" | "files:move" | "metadata:write" | "metadata:override" | "metadata:writeback";

export type ServiceSettingsFields = {
  enabled?: boolean;
  enabledScopes?: Array<Scope>;
  publicBaseUrl?: string;
};

export type WritebackTarget = "sidecar" | "embedded";
