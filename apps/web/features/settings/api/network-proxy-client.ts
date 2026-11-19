import type { NetworkProxyView, ProxyProbe, StoredProxy } from '@/generated/network-proxy';
import { withBasePath } from '@/lib/base-path';

async function request<T>(path: string, method: 'GET' | 'PUT' | 'POST', signal: AbortSignal, body?: StoredProxy) {
  const response = await fetch(withBasePath(`/api/system-settings/network-proxy${path}`), {
    method, signal, credentials: 'same-origin', cache: 'no-store',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  });
  if (!response.ok) throw new Error(`Network proxy request failed (${response.status})`);
  const envelope: { ok: boolean; data: T } = await response.json();
  if (envelope.ok !== true) throw new Error('Invalid network proxy response');
  return envelope.data;
}

export const fetchNetworkProxy = (signal: AbortSignal) => request<NetworkProxyView>('', 'GET', signal);
export const saveNetworkProxy = (body: StoredProxy, signal: AbortSignal) => request<NetworkProxyView>('', 'PUT', signal, body);
export const testNetworkProxy = (body: StoredProxy, signal: AbortSignal) => request<ProxyProbe[]>('/test', 'POST', signal, body);
