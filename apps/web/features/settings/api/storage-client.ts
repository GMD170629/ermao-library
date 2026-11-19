import type { UsagePayload, CategoryUsage } from '@/generated/storage';
import { withBasePath } from '@/lib/base-path';

const categoryIds = ['program', 'database', 'images', 'cache', 'logs', 'backups', 'updates', 'uploads', 'other'] as const;
export type StorageCategory = CategoryUsage['id'];
export type { UsagePayload, CategoryUsage };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseStorageUsage(value: unknown): UsagePayload {
  if (!isRecord(value) || value.ok !== true || !isRecord(value.data)) throw new Error('读取空间用量失败');
  const { root, categories } = value.data;
  if (typeof root !== 'string' || !Array.isArray(categories)) throw new Error('读取空间用量失败');
  const parsed: CategoryUsage[] = categories.map((row: unknown) => {
    if (!isRecord(row) || typeof row.sizeBytes !== 'number' || !Number.isSafeInteger(row.sizeBytes) || row.sizeBytes < 0 || typeof row.clearable !== 'boolean') throw new Error('读取空间用量失败');
    const id = categoryIds.find((key) => key === row.id);
    if (!id) throw new Error('读取空间用量失败');
    return { id, sizeBytes: row.sizeBytes, clearable: row.clearable };
  });
  if (new Set(parsed.map((row) => row.id)).size !== parsed.length) throw new Error('读取空间用量失败');
  return { root, categories: parsed };
}

async function requestStorage(path: string, method: 'GET' | 'DELETE', signal: AbortSignal, category?: StorageCategory): Promise<UsagePayload> {
  const response = await fetch(withBasePath(path), {
    method, credentials: 'same-origin', cache: 'no-store', signal
  });
  if (!response.ok) throw new Error(category ? '清理失败，请重试' : '读取空间用量失败');
  const value: unknown = await response.json();
  const usage = parseStorageUsage(value);
  if (category ? usage.categories.length !== 1 || usage.categories[0]?.id !== category : usage.categories.length !== categoryIds.length) throw new Error('读取空间用量失败');
  return usage;
}

export function getStorageUsage(signal: AbortSignal, category?: StorageCategory) {
  const query = category ? `?category=${category}` : '';
  return requestStorage(`/api/system/storage${query}`, 'GET', signal, category);
}

export function clearStorage(category: StorageCategory, signal: AbortSignal) {
  return requestStorage(`/api/system/storage/${category}`, 'DELETE', signal, category);
}
