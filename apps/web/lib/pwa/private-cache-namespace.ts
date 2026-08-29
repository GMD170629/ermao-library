export const PRIVATE_CACHE_PREFIX = 'shuku-pwa-private-v1-';

export function safePrivateCacheNamespacePart(value: string | number): string {
  return String(value).replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 160);
}

export function privateCacheNamespace(userId: string, authzVersion: number): string {
  const safeUserId = safePrivateCacheNamespacePart(userId);
  const safeAuthzVersion = Number.isSafeInteger(authzVersion) && authzVersion >= 0
    ? safePrivateCacheNamespacePart(authzVersion)
    : '';
  return safeUserId && safeAuthzVersion ? `${safeUserId}-${safeAuthzVersion}` : '';
}

export function privateCacheName(namespace: string, kind: string): string {
  const safeNamespace = safePrivateCacheNamespacePart(namespace);
  const safeKind = safePrivateCacheNamespacePart(kind);
  if (!safeNamespace || safeNamespace !== namespace || !safeKind || safeKind !== kind) {
    throw new Error('PRIVATE_CACHE_NAMESPACE_INVALID');
  }
  return `${PRIVATE_CACHE_PREFIX}${safeNamespace}-${safeKind}`;
}
