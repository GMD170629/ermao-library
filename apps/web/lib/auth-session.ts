export const UNAUTHORIZED_EVENT = 'shuku:unauthorized';
export const SESSION_REFRESH_HEADER = 'X-Shuku-Session-Refresh';

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

export function sessionRefreshRequired(headers: Headers) {
  return headers.get(SESSION_REFRESH_HEADER)?.toLowerCase() === 'required';
}

type SessionRefreshFetch = (
  input: string,
  init: RequestInit
) => Promise<Response>;

export async function requestSessionRefreshIfRequired(
  headers: Headers,
  fetchSessionRefresh: SessionRefreshFetch,
  signal: AbortSignal
): Promise<void> {
  if (!sessionRefreshRequired(headers)) return;
  try {
    await fetchSessionRefresh('/api/auth/session/refresh', {
      method: 'POST',
      cache: 'no-store',
      credentials: 'same-origin',
      signal
    });
  } catch {
    // Session refresh is opportunistic. The foreground /auth/me result remains
    // authoritative, while its existing 401 interceptor handles sign-out.
  }
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
