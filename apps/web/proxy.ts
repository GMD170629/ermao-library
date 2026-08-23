import { NextResponse, type NextRequest } from 'next/server';

const publicPaths = [
  '/login',
  '/setup',
  '/forgot-password',
  '/reset-password',
  '/offline',
  '/api/auth/login',
  '/api/auth/setup',
  '/api/auth/capabilities',
  '/api/auth/password-reset/request',
  '/api/auth/password-reset/confirm',
  '/api/app-config',
  '/api/health',
  '/opds'
];

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  if (
    publicPaths.some((path) => pathname === path || pathname.startsWith(`${path}/`)) ||
    pathname.startsWith('/_next') ||
    pathname.startsWith('/favicon')
  ) {
    return NextResponse.next();
  }

  const isApi = pathname.startsWith('/api/');
  const hasSession = Boolean(request.cookies.get('shuku_session')?.value);
  if (!hasSession) {
    if (isApi) {
      return NextResponse.json({ ok: false, error: { code: 'UNAUTHORIZED', message: '未登录' } }, { status: 401 });
    }
    const login = request.nextUrl.clone();
    const next = `${pathname}${request.nextUrl.search}`;
    login.pathname = '/login';
    login.search = '';
    login.searchParams.set('next', next);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  // FastAPI authenticates this upload endpoint itself. Keeping it outside the
  // Next Proxy preserves streaming instead of cloning and truncating large
  // multipart bodies at Next's request-body buffer limit.
  matcher: ['/((?!api/books/import(?:/|$)|.*\\.).*)']
};
