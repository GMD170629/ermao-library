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

export function currentAuthorizationVersion(userId = currentUserId()) {
  if (typeof window === 'undefined' || !userId) return 0;
  const namespace = window.sessionStorage.getItem(CURRENT_AUTHZ_NAMESPACE_KEY) ?? '';
  const separator = namespace.lastIndexOf(':');
  if (separator < 1 || namespace.slice(0, separator) !== userId) return 0;
  const version = Number(namespace.slice(separator + 1));
  return Number.isSafeInteger(version) && version >= 0 ? version : 0;
}

export function userDevicePreferenceKey(key: string, userId = currentUserId()) {
  return userId ? `${key}:${encodeURIComponent(userId)}` : `${key}:anonymous`;
}

export async function saveAccountPreferences(preferences: Record<string, unknown>) {
  const response = await fetch('/api/auth/preferences', {
    method: 'PATCH',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preferences })
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    throw new Error(payload?.error?.message ?? '保存账户偏好失败');
  }
  return payload.data?.preferences as Record<string, unknown> | undefined;
}
