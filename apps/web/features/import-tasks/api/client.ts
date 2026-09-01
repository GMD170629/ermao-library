export type ImportTaskKind = 'SCAN_LIBRARY' | 'CONTINUE_SOURCE' | 'IMPORT_ASSET';
export type ImportTaskState = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
export type ImportTaskRole = 'PRIMARY' | 'TRACK' | 'PAGE' | 'SIDECAR' | 'SUPPLEMENT';

export type LibraryImportTask = Readonly<{
  id: string;
  kind: ImportTaskKind;
  libraryId: string;
  libraryName: string | null;
  resourceId: string | null;
  resourceTitle: string | null;
  sourceNodeId: string | null;
  sourceName: string | null;
  sourceRelativePath: string | null;
  bookTitle: string | null;
  role: ImportTaskRole | null;
  state: ImportTaskState;
  errorSummary: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}>;

export type ImportTasksPage = Readonly<{
  tasks: LibraryImportTask[];
  summary: Readonly<{ queued: number; running: number; completed: number; failed: number }>;
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}>;

export type ImportLibrary = Readonly<{
  id: string;
  name: string;
  enabled: boolean;
}>;

export type ContinueImportResult = Readonly<{
  taskId: string | null;
  libraryId: string;
  sourceNodeId: string | null;
  requeuedFailed: number;
  enqueued: boolean;
}>;

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.trim() === '') throw new Error(`导入任务响应缺少 ${field}`);
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) return null;
  return requiredString(value, field);
}

function nullableDisplayString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') throw new Error(`导入任务响应缺少 ${field}`);
  return value.trim() ? value : null;
}

function nonNegativeInteger(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : fallback;
}

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : fallback;
}

function taskKind(value: unknown): ImportTaskKind {
  if (value === 'SCAN_LIBRARY' || value === 'CONTINUE_SOURCE' || value === 'IMPORT_ASSET') return value;
  throw new Error('导入任务响应包含无效类型');
}

function taskState(value: unknown): ImportTaskState {
  if (value === 'QUEUED' || value === 'RUNNING' || value === 'SUCCEEDED' || value === 'FAILED') return value;
  throw new Error('导入任务响应包含无效状态');
}

function taskRole(value: unknown): ImportTaskRole | null {
  if (value === null || value === undefined) return null;
  if (value === 'PRIMARY' || value === 'TRACK' || value === 'PAGE' || value === 'SIDECAR' || value === 'SUPPLEMENT') return value;
  throw new Error('导入任务响应包含无效资产角色');
}

export function parseLibraryImportTask(value: unknown): LibraryImportTask {
  if (!isObject(value)) throw new Error('导入任务响应无效');
  return {
    id: requiredString(value.id, 'id'),
    kind: taskKind(value.kind),
    libraryId: requiredString(value.libraryId, 'libraryId'),
    libraryName: nullableDisplayString(value.libraryName, 'libraryName'),
    resourceId: nullableString(value.resourceId, 'resourceId'),
    resourceTitle: nullableDisplayString(value.resourceTitle, 'resourceTitle'),
    sourceNodeId: nullableString(value.sourceNodeId, 'sourceNodeId'),
    sourceName: nullableDisplayString(value.sourceName, 'sourceName'),
    sourceRelativePath: nullableDisplayString(value.sourceRelativePath, 'sourceRelativePath'),
    bookTitle: nullableDisplayString(value.bookTitle, 'bookTitle'),
    role: taskRole(value.role),
    state: taskState(value.state),
    errorSummary: nullableString(value.errorSummary, 'errorSummary'),
    createdAt: requiredString(value.createdAt, 'createdAt'),
    startedAt: nullableString(value.startedAt, 'startedAt'),
    finishedAt: nullableString(value.finishedAt, 'finishedAt')
  };
}

export function parseImportTasksPage(value: unknown): ImportTasksPage {
  if (!isObject(value) || !Array.isArray(value.tasks)) {
    throw new Error('导入任务分页响应无效');
  }
  return {
    tasks: value.tasks.map(parseLibraryImportTask),
    summary: {
      queued: nonNegativeInteger(value.queued),
      running: nonNegativeInteger(value.running),
      completed: nonNegativeInteger(value.completed),
      failed: nonNegativeInteger(value.failed)
    },
    page: positiveInteger(value.page, 1),
    pageSize: positiveInteger(value.pageSize, 10),
    total: nonNegativeInteger(value.total),
    totalPages: positiveInteger(value.totalPages, 1)
  };
}

export function parseImportLibrary(value: unknown): ImportLibrary {
  if (!isObject(value)) throw new Error('书库响应无效');
  return {
    id: requiredString(value.id, 'id'),
    name: requiredString(value.name, 'name'),
    enabled: value.enabled === true
  };
}

export function parseImportLibraries(value: unknown): ImportLibrary[] {
  if (!isObject(value) || !Array.isArray(value.libraries)) {
    throw new Error('书库列表响应无效');
  }
  return value.libraries.map(parseImportLibrary);
}

export function parseImportTaskDetail(value: unknown): LibraryImportTask {
  if (!isObject(value) || !('task' in value)) throw new Error('导入任务详情响应无效');
  return parseLibraryImportTask(value.task);
}

export function parseContinueImportResult(value: unknown): ContinueImportResult {
  if (!isObject(value)) throw new Error('继续导入响应无效');
  return {
    taskId: nullableString(value.taskId, 'taskId'),
    libraryId: requiredString(value.libraryId, 'libraryId'),
    sourceNodeId: nullableString(value.sourceNodeId, 'sourceNodeId'),
    requeuedFailed: nonNegativeInteger(value.requeuedFailed),
    enqueued: value.enqueued === true
  };
}

async function apiJson(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...init });
  const payload: unknown = await response.json().catch(() => null);
  const envelope = isObject(payload) ? payload : {};
  if (!response.ok || envelope.ok === false) {
    const error = isObject(envelope.error) ? envelope.error : {};
    throw new Error(typeof error.message === 'string' ? error.message : `导入请求失败（${response.status}）`);
  }
  return envelope.ok === true && 'data' in envelope ? envelope.data : payload;
}

export async function fetchImportTasks(
  libraryId: string,
  page: number,
  pageSize: number,
  state: ImportTaskState | null = null,
  signal?: AbortSignal
): Promise<ImportTasksPage> {
  const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  if (state) query.set('state', state);
  return parseImportTasksPage(await apiJson(`/api/libraries/${encodeURIComponent(libraryId)}/import-tasks?${query.toString()}`, { signal }));
}

export async function fetchImportLibraries(signal?: AbortSignal): Promise<ImportLibrary[]> {
  return parseImportLibraries(await apiJson('/api/libraries', { signal }));
}

export async function fetchImportTask(taskId: string, signal?: AbortSignal): Promise<LibraryImportTask> {
  return parseImportTaskDetail(await apiJson(`/api/library-import-tasks/${encodeURIComponent(taskId)}`, { signal }));
}

async function continueImport(path: string, signal?: AbortSignal): Promise<ContinueImportResult> {
  return parseContinueImportResult(await apiJson(path, { method: 'POST', signal }));
}

export function continueSourceImport(sourceNodeId: string, signal?: AbortSignal): Promise<ContinueImportResult> {
  return continueImport(`/api/source-nodes/${encodeURIComponent(sourceNodeId)}/continue`, signal);
}

export function continueImportTask(taskId: string, signal?: AbortSignal): Promise<ContinueImportResult> {
  return continueImport(`/api/library-import-tasks/${encodeURIComponent(taskId)}/continue`, signal);
}
