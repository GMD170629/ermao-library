export type LibraryScanSettings = Readonly<{
  watchEnabled: boolean;
  intervalMinutes: number;
}>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload) || !isRecord(payload.error) || typeof payload.error.message !== 'string') return fallback;
  return payload.error.message;
}

export function parseLibraryScanSettings(payload: unknown): LibraryScanSettings {
  if (!isRecord(payload) || payload.ok !== true || !isRecord(payload.data)) {
    throw new Error('读取自动扫描设置失败');
  }
  const { watchEnabled, intervalMinutes } = payload.data;
  if (
    typeof watchEnabled !== 'boolean' ||
    typeof intervalMinutes !== 'number' ||
    !Number.isInteger(intervalMinutes) ||
    intervalMinutes < 5 ||
    intervalMinutes > 1440
  ) {
    throw new Error('自动扫描设置响应格式不正确');
  }
  return { watchEnabled, intervalMinutes };
}

export async function loadLibraryScanSettings(signal?: AbortSignal): Promise<LibraryScanSettings> {
  const response = await fetch('/api/system-settings/library-scan', { signal });
  const payload: unknown = await response.json();
  if (!response.ok) throw new Error(errorMessage(payload, '读取自动扫描设置失败'));
  return parseLibraryScanSettings(payload);
}

export async function saveLibraryScanSettings(settings: LibraryScanSettings): Promise<LibraryScanSettings> {
  const response = await fetch('/api/system-settings/library-scan', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  });
  const payload: unknown = await response.json();
  if (!response.ok) throw new Error(errorMessage(payload, '保存自动扫描设置失败'));
  return parseLibraryScanSettings(payload);
}
