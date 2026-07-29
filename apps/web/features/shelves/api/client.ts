import type { ShelfView, ShelfWriteInput } from '../model/types';
import {
  parseDeletedShelfPayload,
  parseShelfEnvelope,
  parseShelfListPayload,
  parseShelfPayload
} from './schemas';

export class ShelfApiError extends Error {
  constructor(
    message: string,
    readonly code?: string
  ) {
    super(message);
    this.name = 'ShelfApiError';
  }
}

async function readEnvelope<T>(
  response: Response,
  fallback: string,
  parseData: (value: unknown) => T
): Promise<T> {
  let payload: ReturnType<typeof parseShelfEnvelope>;
  try {
    payload = parseShelfEnvelope(await response.json());
  } catch {
    throw new ShelfApiError(fallback);
  }
  if (!response.ok || !payload.ok || payload.data === undefined) {
    throw new ShelfApiError(payload?.error?.message ?? fallback, payload?.error?.code);
  }
  try {
    return parseData(payload.data);
  } catch {
    throw new ShelfApiError(fallback);
  }
}

export async function fetchShelves(signal?: AbortSignal): Promise<ShelfView[]> {
  const data = await readEnvelope(
    await fetch('/api/shelves', { signal }),
    '读取书架失败',
    parseShelfListPayload
  );
  return data.shelves;
}

export async function fetchShelf(
  id: string,
  options: { page: number; pageSize: number; includeIds: boolean; signal?: AbortSignal }
): Promise<ShelfView> {
  const params = new URLSearchParams({
    page: String(options.page),
    pageSize: String(options.pageSize),
    includeBookIds: String(options.includeIds)
  });
  const data = await readEnvelope(
    await fetch(`/api/shelves/${encodeURIComponent(id)}?${params}`, {
      signal: options.signal
    }),
    '读取书架详情失败',
    parseShelfPayload
  );
  return data.shelf;
}

export async function writeShelf(
  id: string | null,
  input: ShelfWriteInput
): Promise<ShelfView> {
  const data = await readEnvelope(
    await fetch(id ? `/api/shelves/${encodeURIComponent(id)}` : '/api/shelves', {
      method: id ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input)
    }),
    '保存书架失败',
    parseShelfPayload
  );
  return data.shelf;
}

export async function deleteShelfById(id: string): Promise<void> {
  await readEnvelope(
    await fetch(`/api/shelves/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    '删除书架失败',
    parseDeletedShelfPayload
  );
}
