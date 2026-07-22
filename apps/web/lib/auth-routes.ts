const publicAppPaths = ['/login', '/setup', '/forgot-password', '/reset-password', '/offline'];

export function isPublicAppPath(pathname: string) {
  return publicAppPaths.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

export function buildLoginRedirectPath(pathname: string, search = '') {
  const normalizedSearch = search ? (search.startsWith('?') ? search : `?${search}`) : '';
  const params = new URLSearchParams({ next: `${pathname || '/'}${normalizedSearch}` });
  return `/login?${params.toString()}`;
}

export function safePostLoginPath(value: string | null | undefined, fallback = '/library') {
  if (!value?.startsWith('/') || value.startsWith('//') || value.includes('\\')) return fallback;

  try {
    const base = new URL('https://shuku.local');
    const target = new URL(value, base);
    if (target.origin !== base.origin || isPublicAppPath(target.pathname)) return fallback;
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return fallback;
  }
}
