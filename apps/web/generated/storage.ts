/* eslint-disable */
// AUTO-GENERATED from the storage FastAPI OpenAPI contract.
// Run pnpm --filter @shuku/web generate:storage-api; do not edit by hand.

export type CategoryUsage = {
  id: "program" | "database" | "images" | "cache" | "logs" | "backups" | "updates" | "uploads" | "other";
  sizeBytes: number;
  clearable: boolean;
};

export type UsagePayload = {
  root: string;
  categories: Array<CategoryUsage>;
};
