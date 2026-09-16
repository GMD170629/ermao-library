/* eslint-disable */
// AUTO-GENERATED from the updates FastAPI OpenAPI contract.
// Run pnpm --filter @shuku/web generate:updates-api; do not edit by hand.

export type AvailableRelease = {
  version: string;
  installable: boolean;
  reason?: string | null;
};

export type Environment = {
  format?: 1;
  platform: string;
  compatibility: string;
};

export type InstallRequest = {
  version: string;
  plan_sha256?: string | null;
  sha256: string;
};

export type Package = {
  version: string;
  format?: 1;
  environment: Environment;
  filename: string;
  size: number;
  sha256: string;
  expanded_size: number;
  file_count: number;
};

export type PreparationState = {
  phase?: "idle" | "downloading" | "verifying" | "extracting" | "ready" | "failed" | "requested" | "checking" | "stopping" | "backup" | "copying" | "starting" | "success";
  target?: Package | ReleaseReference | null;
  summary?: PreparationSummary | null;
  downloaded?: number;
  started_at?: string | null;
  updated_at?: string | null;
  failed_phase?: string | null;
  error?: string | null;
};

export type PreparationSummary = {
  plan_sha256?: string | null;
  dependency_identity: string;
  baseline: string;
  code_sha256: string;
  keep: number;
  install: number;
  remove: number;
  total_bytes: number;
  dependency_bytes: number;
  verified_artifacts?: number;
};

export type PrepareRequest = {
  version: string;
};

export type ReleaseReference = {
  version: string;
  format?: 2;
  environment: Environment;
  filename: string;
  size: number;
  sha256: string;
};

export type RuntimeInfo = {
  current_version: string;
  supported: boolean;
  install_protocol?: number;
};

export type UpdateCheck = {
  current_version: string;
  supported: boolean;
  releases: Array<AvailableRelease>;
};
