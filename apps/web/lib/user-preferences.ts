import { apiV2Fetch } from '@/lib/api-v2';
import type { AccountPreferences, ProblemDetails } from '@/generated/api-v2';
export const CURRENT_USER_ID_KEY = 'shuku:session:user-id';
export const CURRENT_AUTHZ_NAMESPACE_KEY = 'shuku:session:authz-namespace';

export function setCurrentUserNamespace(userId: string, authzVersion: number) {
  if (typeof window === 'undefined') return;
  window.sessionStorage.setItem(CURRENT_USER_ID_KEY, userId);
  window.sessionStorage.setItem(CURRENT_AUTHZ_NAMESPACE_KEY, `${userId}:${authzVersion}`);
}

export function clearCurrentUserNamespace() {
  if (typeof window === 'undefined') return;
  window.sessionStorage.removeItem(CURRENT_USER_ID_KEY);
  window.sessionStorage.removeItem(CURRENT_AUTHZ_NAMESPACE_KEY);
}

export function currentUserId() {
  if (typeof window === 'undefined') return '';
  return window.sessionStorage.getItem(CURRENT_USER_ID_KEY) ?? '';
}

export function userDevicePreferenceKey(key: string, userId = currentUserId()) {
  return userId ? `${key}:${encodeURIComponent(userId)}` : `${key}:anonymous`;
}

export async function saveAccountPreferences(preferences: Record<string, unknown>) {
  const response = await apiV2Fetch('/api/v2/account/preferences', {
    method: 'PATCH',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values: preferences })
  });
  const payload = await response.json().catch(() => null) as AccountPreferences | ProblemDetails | null;
  if (!response.ok || !payload || !('values' in payload)) {
    throw new Error(payload && 'detail' in payload ? payload.detail : '保存账户偏好失败');
  }
  return payload.values;
}
