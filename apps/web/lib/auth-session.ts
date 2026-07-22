export const UNAUTHORIZED_EVENT = 'shuku:unauthorized';

const nonRedirectingAuthPaths = [
  '/api/auth/login',
  '/api/auth/setup',
  '/api/auth/setup/status',
  '/api/auth/capabilities',
  '/api/auth/password-reset/request',
  '/api/auth/password-reset/confirm'
];

export function shouldHandleUnauthorizedPath(pathname: string) {
  if (!pathname.includes('/api/')) return false;
  return !nonRedirectingAuthPaths.some((path) => pathname.endsWith(path));
}

export function installUnauthorizedFetchInterceptor() {
  const originalFetch = window.fetch;
  const interceptedFetch: typeof window.fetch = async (input, init) => {
    const response = await originalFetch.call(window, input, init);
    if (response.status !== 401) return response;

    const inputUrl = typeof input === 'string'
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
    const url = new URL(inputUrl, window.location.origin);
    if (url.origin === window.location.origin && shouldHandleUnauthorizedPath(url.pathname)) {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT, { detail: { pathname: url.pathname } }));
    }
    return response;
  };

  window.fetch = interceptedFetch;
  return () => {
    if (window.fetch === interceptedFetch) window.fetch = originalFetch;
  };
}
