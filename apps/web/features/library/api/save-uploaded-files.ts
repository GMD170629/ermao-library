type JsonRecord = Record<string, unknown>;

export type SavedUploadFile = {
  file: string;
  sourcePath: string;
  sizeBytes: number;
  monitoringStatus: 'WATCHING' | 'NOT_MONITORED';
};

export type SaveUploadedFilesResult =
  | {
    kind: 'saved';
    saved: number;
    autoImport: boolean;
    files: SavedUploadFile[];
  }
  | { kind: 'rejected'; code: string | null; message: string }
  | { kind: 'transport-failed' }
  | { kind: 'invalid-response' };

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseSavedUploadFile(value: unknown): SavedUploadFile | null {
  if (!isRecord(value)) return null;
  const monitoringStatus = value.monitoringStatus;
  if (
    typeof value.file !== 'string'
    || typeof value.sourcePath !== 'string'
    || typeof value.sizeBytes !== 'number'
    || (monitoringStatus !== 'WATCHING' && monitoringStatus !== 'NOT_MONITORED')
  ) {
    return null;
  }
  return {
    file: value.file,
    sourcePath: value.sourcePath,
    sizeBytes: value.sizeBytes,
    monitoringStatus
  };
}

export function parseSaveUploadedFilesResponse(payload: unknown): SaveUploadedFilesResult {
  if (!isRecord(payload)) return { kind: 'invalid-response' };
  if (payload.ok !== true) {
    const error = isRecord(payload.error) ? payload.error : null;
    return typeof error?.message === 'string'
      ? {
          kind: 'rejected',
          code: typeof error.code === 'string' ? error.code : null,
          message: error.message
        }
      : { kind: 'invalid-response' };
  }
  if (!isRecord(payload.data) || !Array.isArray(payload.data.results)) {
    return { kind: 'invalid-response' };
  }
  const files = payload.data.results.map(parseSavedUploadFile);
  if (
    files.some((file) => file === null)
    || typeof payload.data.saved !== 'number'
    || typeof payload.data.autoImport !== 'boolean'
  ) {
    return { kind: 'invalid-response' };
  }
  return {
    kind: 'saved',
    saved: payload.data.saved,
    autoImport: payload.data.autoImport,
    files: files.filter((file): file is SavedUploadFile => file !== null)
  };
}

export async function postUploadedFiles(form: FormData): Promise<SaveUploadedFilesResult> {
  try {
    const response = await fetch('/api/works/import', { method: 'POST', body: form });
    const payload: unknown = await response.json();
    return parseSaveUploadedFilesResponse(payload);
  } catch {
    return { kind: 'transport-failed' };
  }
}
