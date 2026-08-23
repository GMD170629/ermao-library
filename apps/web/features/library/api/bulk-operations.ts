export type BulkBookOperationResult = {
  updated: number;
  changedValues: number;
  operationId: string;
};

export type BulkBookCoverResult = {
  updated: number;
  skipped: Array<{ bookId: string; reason: string }>;
  operationId: string;
};

export type BulkFindReplaceInput = {
  ids: string[];
  field: 'title' | 'author' | 'description' | 'seriesName' | 'tags' | 'resourceTitle';
  find: string;
  replacement: string;
  regex: boolean;
  caseSensitive: boolean;
  startNumber: number;
};

export type BulkFindReplacePreview = {
  changedBooks: number;
  changedValues: number;
  items: Array<{
    bookId: string;
    title: string;
    before: string | string[];
    after: string | string[];
    resourceId?: string;
  }>;
};

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`Invalid bulk operation field: ${field}`);
  return value;
}

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid bulk operation field: ${field}`);
  }
  return value;
}

async function readData(response: Response, fallback: string): Promise<unknown> {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok || !isObject(payload) || payload.ok !== true || !('data' in payload)) {
    const message = isObject(payload) && isObject(payload.error) && typeof payload.error.message === 'string'
      ? payload.error.message
      : fallback;
    throw new Error(message);
  }
  return payload.data;
}

function parseOperationResult(value: unknown): BulkBookOperationResult {
  if (!isObject(value) || !isObject(value.operation)) {
    throw new Error('Invalid bulk operation response');
  }
  return {
    updated: requiredNumber(value.updated, 'updated'),
    changedValues: requiredNumber(value.changedValues, 'changedValues'),
    operationId: requiredString(value.operation.id, 'operation.id')
  };
}

export function parseBulkFindReplacePreview(value: unknown): BulkFindReplacePreview {
  if (!isObject(value) || !Array.isArray(value.items)) {
    throw new Error('Invalid bulk find-replace preview');
  }
  return {
    changedBooks: requiredNumber(value.changedBooks, 'changedBooks'),
    changedValues: requiredNumber(value.changedValues, 'changedValues'),
    items: value.items.map((item) => {
      if (!isObject(item)) throw new Error('Invalid bulk find-replace item');
      const before = item.before;
      const after = item.after;
      if (typeof before !== 'string' && !Array.isArray(before)) {
        throw new Error('Invalid bulk find-replace item before');
      }
      if (typeof after !== 'string' && !Array.isArray(after)) {
        throw new Error('Invalid bulk find-replace item after');
      }
      const resourceId = item.resourceId === null || item.resourceId === undefined
        ? undefined
        : requiredString(item.resourceId, 'resourceId');
      return {
        bookId: requiredString(item.bookId, 'bookId'),
        title: requiredString(item.title, 'title'),
        before: Array.isArray(before) ? before.map((entry) => requiredString(entry, 'before')) : before,
        after: Array.isArray(after) ? after.map((entry) => requiredString(entry, 'after')) : after,
        ...(resourceId ? { resourceId } : {})
      };
    })
  };
}

async function postJson(path: string, body: object, fallback: string): Promise<unknown> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(body)
  });
  return readData(response, fallback);
}

export async function updateBulkBookMetadata(input: {
  ids: string[];
  fields: Record<string, string>;
  addTags: string[];
  removeTags: string[];
}): Promise<BulkBookOperationResult> {
  return parseOperationResult(await postJson(
    '/api/library/operations/books/metadata',
    input,
    '批量更新元数据失败'
  ));
}

export async function previewBulkBookFindReplace(
  input: BulkFindReplaceInput
): Promise<BulkFindReplacePreview> {
  return parseBulkFindReplacePreview(await postJson(
    '/api/library/operations/books/find-replace-preview',
    input,
    '生成预览失败'
  ));
}

export async function applyBulkBookFindReplace(
  input: BulkFindReplaceInput
): Promise<BulkBookOperationResult> {
  return parseOperationResult(await postJson(
    '/api/library/operations/books/find-replace',
    input,
    '批量查找替换失败'
  ));
}

export async function updateBulkBookShelfMembership(input: {
  ids: string[];
  shelfId: string;
  membership: 'ADD' | 'REMOVE';
}): Promise<BulkBookOperationResult> {
  return parseOperationResult(await postJson(
    '/api/library/operations/books/shelf-membership',
    input,
    '批量更新书架失败'
  ));
}

export async function updateBulkBookReadingStatus(input: {
  ids: string[];
  status: 'UNREAD' | 'FINISHED';
}): Promise<BulkBookOperationResult> {
  return parseOperationResult(await postJson(
    '/api/library/operations/books/reading-status',
    input,
    '批量更新阅读状态失败'
  ));
}

export async function updateBulkBookCovers(input: {
  ids: string[];
  action: 'crop' | 'regenerate' | 'compress' | 'replace';
  ratio: string;
  quality: number;
  maxDimension: number;
  cover?: File;
}): Promise<BulkBookCoverResult> {
  const form = new FormData();
  form.append('ids', JSON.stringify(input.ids));
  form.append('action', input.action);
  form.append('ratio', input.ratio);
  form.append('quality', String(input.quality));
  form.append('maxDimension', String(input.maxDimension));
  if (input.cover) form.append('cover', input.cover);
  const response = await fetch('/api/library/operations/books/covers', {
    method: 'POST',
    credentials: 'same-origin',
    body: form
  });
  const value = await readData(response, '批量处理封面失败');
  if (!isObject(value) || !Array.isArray(value.skipped) || !isObject(value.operation)) {
    throw new Error('Invalid bulk cover response');
  }
  return {
    updated: requiredNumber(value.updated, 'updated'),
    skipped: value.skipped.map((item) => {
      if (!isObject(item)) throw new Error('Invalid bulk cover skip');
      return {
        bookId: requiredString(item.bookId, 'skipped.bookId'),
        reason: requiredString(item.reason, 'skipped.reason')
      };
    }),
    operationId: requiredString(value.operation.id, 'operation.id')
  };
}
