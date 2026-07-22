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
  '/api/health'
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

  const isApi = pathname.startsWith('/api/');
  const hasSession = Boolean(request.cookies.get('shuku_session')?.value);
  if (!hasSession) {
    if (isApi) {
      return NextResponse.json({ ok: false, error: { message: '未登录' } }, { status: 401 });
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
