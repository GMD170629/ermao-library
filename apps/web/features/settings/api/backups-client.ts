import type { Backup, BackupCompatibilityResponse, BackupProblemResponse } from '../../../generated/backup';
import { withBasePath } from '../../../lib/base-path';
import { readBoundedResponse } from '../../../shared/api/bounded-response';

export type BackupItem = Omit<Backup, 'filename' | 'compatibility'> & {
  filename: string;
  compatibility: BackupCompatibilityResponse;
};

export class BackupApiError extends Error {
  constructor(message: string, readonly messageEn: string) {
    super(message);
  }
}

function invalidResponse(): never {
  throw new BackupApiError('服务器返回的备份响应格式无效', 'The server returned an invalid backup response');
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function record(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) return invalidResponse();
  return value;
}
function text(value: unknown): string {
  if (typeof value !== 'string') return invalidResponse();
  return value;
}
function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}
function parseProblem(value: unknown): BackupProblemResponse | null {
  if (value === null) return null;
  const data = record(value);
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(record(data.params))) params[key] = text(value);
  return { code: text(data.code), message: text(data.message), messageEn: text(data.messageEn), params };
}
export function parseBackup(value: unknown): BackupItem {
  const data = record(value);
  const check = record(data.compatibility);
  if (!['compatible', 'incompatible', 'unreadable'].includes(text(check.status))) return invalidResponse();
  const status = check.status === 'compatible' ? 'compatible' : check.status === 'incompatible' ? 'incompatible' : 'unreadable';
  const problem = parseProblem(check.problem);
  if ((status === 'compatible') !== (problem === null)) return invalidResponse();
  if (typeof data.sizeBytes !== 'number' || !Number.isFinite(data.sizeBytes) || data.sizeBytes < 0) return invalidResponse();
  const counts: Record<string, number> = {};
  if (data.counts != null) {
    for (const [key, value] of Object.entries(record(data.counts))) {
      if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) return invalidResponse();
      counts[key] = value;
    }
  }
  if (!Number.isFinite(Date.parse(text(data.createdAt)))) return invalidResponse();
  return {
    id: text(data.id), name: text(data.name), filename: text(data.filename),
    kind: data.kind == null ? null : text(data.kind), sizeBytes: data.sizeBytes,
    createdAt: text(data.createdAt), counts: data.counts == null ? null : counts,
    compatibility: { status, problem, formatVersion: nullableText(check.formatVersion),
      databaseRevision: nullableText(check.databaseRevision), requiredFormatVersion: text(check.requiredFormatVersion),
      requiredDatabaseRevision: text(check.requiredDatabaseRevision) }
  };
}

async function request(path: string, signal: AbortSignal, method = 'GET', body?: FormData | string): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(withBasePath(path), { method, body, signal, cache: 'no-store', credentials: 'same-origin',
      headers: typeof body === 'string' ? { 'Content-Type': 'application/json' } : undefined });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new BackupApiError('无法连接服务器，未收到操作结果；请检查网络后刷新备份列表确认',
      'Could not reach the server. No operation result was received; check your connection and refresh the backup list to confirm.');
  }
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder().decode(await readBoundedResponse(response, 16 * 1024 * 1024)));
  } catch (error) {
    if (signal.aborted) throw error;
    throw new BackupApiError(`服务器响应无法解析（HTTP ${response.status}）`, `Cannot parse the server response (HTTP ${response.status})`);
  }
  const envelope = record(value);
  if (!response.ok || envelope.ok !== true) {
    const error = record(envelope.error);
    const params = error.params == null ? {} : record(error.params);
    throw new BackupApiError(text(error.message), typeof params.messageEn === 'string' ? params.messageEn : text(error.message));
  }
  return record(envelope.data);
}

export async function loadBackups(signal: AbortSignal): Promise<BackupItem[]> {
  const result = await request('/api/backups', signal);
  if (!Array.isArray(result.backups)) return invalidResponse();
  return result.backups.map(parseBackup);
}
export async function createBackup(signal: AbortSignal): Promise<BackupItem> {
  return parseBackup((await request('/api/backups', signal, 'POST')).backup);
}
export async function uploadBackup(file: File, signal: AbortSignal): Promise<BackupItem> {
  const data = new FormData();
  data.set('file', file);
  return parseBackup((await request('/api/backups/upload', signal, 'POST', data)).backup);
}
export async function restoreBackup(id: string, signal: AbortSignal): Promise<void> {
  const data = await request(`/api/backups/${encodeURIComponent(id)}/restore`, signal, 'POST', JSON.stringify({ confirm: true, confirmText: 'RESTORE' }));
  if (data.restored !== true || data.id !== id) invalidResponse();
}
export async function deleteBackup(id: string, signal: AbortSignal): Promise<void> {
  const data = await request(`/api/backups/${encodeURIComponent(id)}`, signal, 'DELETE');
  if (data.deleted !== true) throw new BackupApiError('备份文件已不存在，请刷新列表', 'The backup file no longer exists; refresh the list');
}
export function backupDownloadUrl(id: string): string {
  return withBasePath(`/api/backups/${encodeURIComponent(id)}/download`);
}
export function backupErrorMessage(error: unknown, locale: string): string {
  if (error instanceof BackupApiError) {
    const message = locale === 'en-US' ? error.messageEn : error.message;
    return message;
  }
  return error instanceof Error ? error.message : String(error);
}
