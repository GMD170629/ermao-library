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
  target?: Package | null;
  downloaded?: number;
  started_at?: string | null;
  updated_at?: string | null;
  failed_phase?: string | null;
  error?: string | null;
};

export type PrepareRequest = {
  version: string;
};

export type RuntimeInfo = {
  current_version: string;
  supported: boolean;
};

export type UpdateCheck = {
  current_version: string;
  supported: boolean;
  releases: Array<AvailableRelease>;
};
