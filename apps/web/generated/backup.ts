/* eslint-disable */
// AUTO-GENERATED from the backup FastAPI OpenAPI contract.
// Export FastAPI OpenAPI with scripts/export_openapi.py, then run node scripts/generate-reader-api.mjs <openapi.json> generated/backup.ts backup from apps/web; do not edit by hand.

export type Backup = {
  id: string;
  kind?: string | null;
  name: string;
  filename?: string | null;
  sizeBytes: number;
  createdAt: string;
  counts?: {
    [key: string]: number | null | undefined;
  } | null;
  compatibility?: BackupCompatibilityResponse | null;
};

export type BackupCompatibilityResponse = {
  status: "compatible" | "incompatible" | "unreadable";
  problem: BackupProblemResponse | null;
  formatVersion: string | null;
  databaseRevision: string | null;
  requiredFormatVersion: string;
  requiredDatabaseRevision: string;
};

export type BackupDeletePayload = {
  deleted: boolean;
  id: string;
};

export type BackupPayload = {
  backup: Backup;
};

export type BackupProblemResponse = {
  code: string;
  message: string;
  messageEn: string;
  params: {
    [key: string]: string | null | undefined;
  };
};

export type BackupRestorePayload = {
  id: string;
  restored: true;
  restoredAt: string;
  counts: {
    [key: string]: number | null | undefined;
  } | null;
  restoredCounts: {
    [key: string]: number | null | undefined;
  };
  actualCounts: {
    [key: string]: number | null | undefined;
  };
};

export type BackupRestoreRequest = {
  confirm?: boolean | null;
  confirmText?: string | null;
};

export type BackupsPayload = {
  backups: Array<Backup>;
};
