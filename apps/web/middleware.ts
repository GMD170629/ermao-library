import { NextResponse, type NextRequest } from 'next/server';

const publicPaths = [
  '/login',
  '/setup',
  '/forgot-password',
  '/reset-password',
  '/offline',
  '/api/v2/auth/login',
  '/api/v2/auth/setup',
  '/api/v2/auth/setup/status',
  '/api/v2/auth/capabilities',
  '/api/v2/auth/password-reset/request',
  '/api/v2/auth/password-reset/confirm',
  '/api/v2/operations/health'
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    publicPaths.some((path) => pathname === path || pathname.startsWith(`${path}/`)) ||
    pathname.startsWith('/_next') ||
    pathname.startsWith('/favicon')
  ) {
    return NextResponse.next();
  }

  const isApi = pathname.startsWith('/api/v2/');
  const hasSession = Boolean(request.cookies.get('shuku_v2_session')?.value);
  if (!hasSession) {
    if (isApi) {
      return NextResponse.json(
        {
          type: 'https://shuku.app/problems/authentication-required',
          title: 'Authentication required',
          status: 401,
          code: 'AUTHENTICATION_REQUIRED',
          detail: '未登录',
          params: {}
        },
        {
          status: 401,
          headers: { 'Content-Type': 'application/problem+json' }
        }
      );
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
  matcher: ['/((?!.*\\.).*)']
};
