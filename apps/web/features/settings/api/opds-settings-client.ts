export type OpdsSystemSettings = {
  enabled: boolean;
  configured: boolean;
  publicBaseUrl?: string;
  catalogUrl?: string;
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

function parseSettings(payload: unknown): OpdsSystemSettings {
  if (!isRecord(payload) || payload.ok !== true || !isRecord(payload.data)) {
    throw new Error('读取 OPDS 配置失败');
  }
  if (typeof payload.data.enabled !== 'boolean' || typeof payload.data.configured !== 'boolean') {
    throw new Error('OPDS 配置响应格式不正确');
  }
  return {
    enabled: payload.data.enabled,
    configured: payload.data.configured,
    publicBaseUrl: typeof payload.data.publicBaseUrl === 'string' ? payload.data.publicBaseUrl : undefined,
    catalogUrl: typeof payload.data.catalogUrl === 'string' ? payload.data.catalogUrl : undefined
  };
}

export async function loadOpdsSettings(signal?: AbortSignal): Promise<OpdsSystemSettings> {
  const response = await fetch('/api/system-settings/opds', { signal });
  const payload: unknown = await response.json();
  if (!response.ok) throw new Error(errorMessage(payload, '读取 OPDS 配置失败'));
  return parseSettings(payload);
}

export async function saveOpdsSettings(enabled: boolean, publicBaseUrl?: string): Promise<OpdsSystemSettings> {
  const response = await fetch('/api/system-settings/opds', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled, publicBaseUrl })
  });
  const payload: unknown = await response.json();
  if (!response.ok) throw new Error(errorMessage(payload, '保存 OPDS 配置失败'));
  return parseSettings(payload);
}
