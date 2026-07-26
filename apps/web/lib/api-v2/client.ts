import { LOCALE_COOKIE_NAME, normalizeLocale } from '../../i18n/config';
import { withBasePath } from '../base-path';

export type ProblemDetails = {
  type: string;
  title: string;
  status: number;
  code: string;
  detail: string;
  params: Record<string, unknown>;
  traceId?: string;
};

export class ApiV2Error extends Error {
  readonly problem: ProblemDetails;

  constructor(problem: ProblemDetails) {
    super(problem.detail || problem.title);
    this.name = 'ApiV2Error';
    this.problem = problem;
  }
}

function activeLocale() {
  if (typeof document === 'undefined') return 'zh-CN';
  const prefix = `${LOCALE_COOKIE_NAME}=`;
  const cookieValue = document.cookie
    .split(';')
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix))
    ?.slice(prefix.length);
  return normalizeLocale(cookieValue ? decodeURIComponent(cookieValue) : document.documentElement.lang);
}

function assertV2Path(path: string) {
  if (!path.startsWith('/api/v2/')) {
    throw new TypeError(`apiV2Fetch only accepts /api/v2 routes: ${path}`);
  }
}

export async function apiV2Fetch(path: string, init: RequestInit = {}) {
  assertV2Path(path);
  const headers = new Headers(init.headers);
  headers.set('Accept-Language', activeLocale());
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');
  return fetch(withBasePath(path), {
    credentials: 'same-origin',
    ...init,
    headers
  });
}

export async function apiV2Request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiV2Fetch(path, init);
  if (response.status === 204) return undefined as T;
  const payload: unknown = await response.json();
  if (!response.ok) {
    const problem = payload as Partial<ProblemDetails>;
    throw new ApiV2Error({
      type: problem.type ?? 'about:blank',
      title: problem.title ?? 'Request failed',
      status: problem.status ?? response.status,
      code: problem.code ?? 'REQUEST_FAILED',
      detail: problem.detail ?? response.statusText,
      params: problem.params ?? {},
      traceId: problem.traceId
    });
  }
  return payload as T;
}
