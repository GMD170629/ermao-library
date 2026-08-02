export const importPreferenceSettingKeys = {
  stabilityEnabled: 'import.stabilityCheck.enabled',
  stabilitySeconds: 'import.stabilityCheck.seconds',
  allowedExtensions: 'import.allowedExtensions',
  ignorePatterns: 'import.ignorePatterns'
} as const;

export type ImportPreferenceValues = {
  [importPreferenceSettingKeys.stabilityEnabled]: boolean;
  [importPreferenceSettingKeys.stabilitySeconds]: number;
  [importPreferenceSettingKeys.allowedExtensions]: string[];
  [importPreferenceSettingKeys.ignorePatterns]: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload) || !isRecord(payload.error) || typeof payload.error.message !== 'string') {
    return fallback;
  }
  return payload.error.message;
}

export async function loadImportPreferenceSettings(): Promise<Record<string, unknown> | undefined> {
  const response = await fetch('/api/system-settings');
  const payload: unknown = await response.json();
  if (!response.ok || !isRecord(payload) || payload.ok !== true) {
    throw new Error(errorMessage(payload, '读取导入偏好失败'));
  }
  if (!isRecord(payload.data) || !isRecord(payload.data.settings)) {
    return undefined;
  }
  return payload.data.settings;
}

export async function saveImportPreferenceSettings(settings: ImportPreferenceValues): Promise<void> {
  const response = await fetch('/api/system-settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings })
  });
  const payload: unknown = await response.json();
  if (!response.ok || !isRecord(payload) || payload.ok !== true) {
    throw new Error(errorMessage(payload, '保存导入偏好失败'));
  }
}
