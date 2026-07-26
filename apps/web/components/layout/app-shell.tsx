'use client';

import { apiV2Fetch } from '@/lib/api-v2';
import type {
  AccountResponse,
  Page_ShelfResponse_,
  Page_WorkResponse_
} from '@/generated/api-v2';

import {
  ArrowLeft,
  BookOpen,
  ChevronRight,
  Grid2X2,
  Home,
  Plus,
  Search,
  X
} from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode
} from 'react';
import { buildLoginRedirectPath, isPublicAppPath, safePostLoginPath } from '../../lib/auth-routes';
import { accountAuthorizationVersion } from '../../lib/account-authorization';
import { installUnauthorizedFetchInterceptor, UNAUTHORIZED_EVENT } from '../../lib/auth-session';
import { withBasePath } from '../../lib/base-path';
import { DEFAULT_ACCOUNT_AVATAR_PATH, PRODUCT_NAME } from '../../lib/brand';
import { clearCurrentUserNamespace, setCurrentUserNamespace, userDevicePreferenceKey } from '../../lib/user-preferences';
import { Cover } from '../book/cover';
import { clearPrivatePwaStorage, PwaClient } from '../system/pwa-client';
import { cn } from '../ui/cn';
import { useToast } from '../ui/feedback';
import { useAudioPlayback } from '../../features/audio/audio-playback-provider';
import { isSettingsItemActive, settingsGroups, settingsItemAllowed, type SettingsAuthorization } from '../../features/settings/center/settings-secondary-nav';
import { MOBILE_NAVIGATION_DRAWER_ID, MobileNavigationProvider } from './mobile-navigation';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

const primaryNavItems = [
  { href: '/', icon: Home, label: '首页' }
];

const libraryNavItems = [
  { href: '/library', icon: Grid2X2, label: '全部' },
  { href: '/library?status=READING', icon: BookOpen, label: '进行中' }
];

const shellSurfaces = {
  app: { background: '#FBFAF8', colorScheme: 'light', statusBarStyle: 'black-translucent' },
  reader: { background: '#FDF6EA', colorScheme: 'light', statusBarStyle: 'default' },
  login: { background: '#F8FAFC', colorScheme: 'light', statusBarStyle: 'black-translucent' },
  setup: { background: '#E8DCC7', colorScheme: 'light', statusBarStyle: 'black-translucent' },
  offline: { background: '#020617', colorScheme: 'dark', statusBarStyle: 'black-translucent' }
} satisfies Record<string, { background: string; colorScheme: 'light' | 'dark'; statusBarStyle: 'default' | 'black-translucent' }>;

type BookSearchItem = {
  id: string;
  title: string;
  author: string;
  coverUrl: string;
  format: string;
};

type ShelfSummary = {
  id: string;
  name: string;
};

type SessionStatus = 'checking' | 'authenticated' | 'unavailable' | 'redirecting';

function accountUser(account: AccountResponse) {
  return {
    id: account.id,
    email: account.email,
    name: account.displayName,
    role: account.role,
    locale: account.locale,
    avatarUrl: null
  };
}

function accountAuthorization(account: AccountResponse): SettingsAuthorization & {
  authzVersion: number;
} {
  return {
    isAdmin: account.role === 'admin',
    canManageSystem: account.scopes.includes('operations:write'),
    authzVersion: accountAuthorizationVersion(account)
  };
}

function ensureMeta(name: string) {
  const existing = document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
  if (existing) return { meta: existing, created: false };
  const meta = document.createElement('meta');
  meta.setAttribute('name', name);
  document.head.appendChild(meta);
  return { meta, created: true };
}

function isActive(pathname: string, currentSearch: URLSearchParams, href: string) {
  const [targetPath, targetQuery = ''] = href.split('?');
  const pathMatches = targetPath === '/' ? pathname === '/' : pathname === targetPath || pathname.startsWith(`${targetPath}/`);
  if (!pathMatches) return false;

  const targetSearch = new URLSearchParams(targetQuery);
  if (targetSearch.size > 0) {
    return Array.from(targetSearch.entries()).every(([key, value]) => currentSearch.get(key) === value);
  }

  if (targetPath === '/library') return !currentSearch.get('status');
  if (targetPath === '/shelves') return !currentSearch.get('shelf') && currentSearch.get('create') !== '1';
  return true;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { t: i18nAttribute, setLocale } = useAttributeI18n();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [user, setUser] = useState<{ id?: string; email: string; name: string; role: string; avatarUrl?: string | null } | null>(null);
  const [authorization, setAuthorization] = useState<(SettingsAuthorization & { authzVersion?: number }) | null>(null);
  const [avatarFailed, setAvatarFailed] = useState(false);
  const [shelves, setShelves] = useState<ShelfSummary[]>([]);
  const [librarySearch, setLibrarySearch] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);
  const [searchBooks, setSearchBooks] = useState<BookSearchItem[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchActiveIndex, setSearchActiveIndex] = useState(0);
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>('checking');
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const searchFormRef = useRef<HTMLFormElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const mobileSearchInputRef = useRef<HTMLInputElement>(null);
  const authRedirectingRef = useRef(false);
  const appMainRef = useRef<HTMLElement>(null);
  const drawerPanelRef = useRef<HTMLElement>(null);
  const drawerCloseButtonRef = useRef<HTMLButtonElement>(null);
  const drawerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const drawerOpenRef = useRef(false);
  const drawerHistoryEntryRef = useRef(false);
  const drawerPendingNavigationRef = useRef<string | null>(null);
  const restoreDrawerTriggerFocusRef = useRef(true);
  const focusMobileSearchOnOpenRef = useRef(false);
  const drawerSwipeStartRef = useRef<{ x: number; y: number } | null>(null);
  const toast = useToast();
  const audioPlayback = useAudioPlayback();
  const isReader = pathname.startsWith('/reader/');
  const isSetupPage = pathname === '/setup';
  const isAuthPage = pathname === '/login' || isSetupPage || pathname === '/forgot-password' || pathname === '/reset-password';
  const isOffline = pathname === '/offline';
  const isSettingsMode = pathname.startsWith('/settings');
  const isProtectedPage = !isPublicAppPath(pathname);
  const currentSearchString = searchParams.toString();
  const currentSearch = useMemo(() => new URLSearchParams(currentSearchString), [currentSearchString]);
  const shellSurface = isReader
    ? shellSurfaces.reader
    : isSetupPage
      ? shellSurfaces.setup
      : isAuthPage
      ? shellSurfaces.login
      : isOffline
        ? shellSurfaces.offline
        : shellSurfaces.app;

  const finishClosingMobileDrawer = useCallback((restoreFocus: boolean) => {
    drawerOpenRef.current = false;
    restoreDrawerTriggerFocusRef.current = restoreFocus;
    setMobileDrawerOpen(false);
  }, []);

  const closeMobileDrawer = useCallback((restoreFocus = true) => {
    restoreDrawerTriggerFocusRef.current = restoreFocus;
    if (drawerHistoryEntryRef.current) {
      window.history.back();
      return;
    }
    finishClosingMobileDrawer(restoreFocus);
  }, [finishClosingMobileDrawer]);

  const openMobileDrawer = useCallback((trigger: HTMLButtonElement) => {
    if (window.matchMedia('(min-width: 1024px)').matches || drawerOpenRef.current) return;
    drawerTriggerRef.current = trigger;
    drawerOpenRef.current = true;
    restoreDrawerTriggerFocusRef.current = true;
    setMobileDrawerOpen(true);
    if (!drawerHistoryEntryRef.current) {
      const currentState = typeof window.history.state === 'object' && window.history.state !== null
        ? window.history.state as Record<string, unknown>
        : {};
      window.history.pushState({ ...currentState, shukuMobileDrawer: true }, '', window.location.href);
      drawerHistoryEntryRef.current = true;
    }
  }, []);

  const navigateFromMobileDrawer = useCallback((href: string) => {
    drawerPendingNavigationRef.current = href;
    restoreDrawerTriggerFocusRef.current = false;
    if (drawerHistoryEntryRef.current) {
      window.history.back();
      return;
    }
    finishClosingMobileDrawer(false);
    router.push(href);
  }, [finishClosingMobileDrawer, router]);

  const handleMobileDrawerLink = useCallback((event: ReactMouseEvent<HTMLAnchorElement>, href: string) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigateFromMobileDrawer(href);
  }, [navigateFromMobileDrawer]);

  const redirectToLogin = useCallback(() => {
    if (!isProtectedPage || authRedirectingRef.current) return;
    authRedirectingRef.current = true;
    setSessionStatus('redirecting');
    clearCurrentUserNamespace();
    void clearPrivatePwaStorage().catch(() => undefined);
    router.replace(buildLoginRedirectPath(pathname, currentSearchString));
  }, [currentSearchString, isProtectedPage, pathname, router]);

  useEffect(() => installUnauthorizedFetchInterceptor(), []);

  useEffect(() => {
    if (!isProtectedPage) {
      authRedirectingRef.current = false;
      return undefined;
    }
    window.addEventListener(UNAUTHORIZED_EVENT, redirectToLogin);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, redirectToLogin);
  }, [isProtectedPage, redirectToLogin]);

  useEffect(() => {
    if (!isProtectedPage) return undefined;

    let active = true;
    const controller = new AbortController();
    setSessionStatus((current) => current === 'authenticated' ? current : 'checking');
    apiV2Fetch('/api/v2/account', {
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null) as AccountResponse | null;
        if (!active) return;
        if (response.status === 401) {
          redirectToLogin();
          return;
        }
        if (response.ok && payload?.id) {
          const nextUser = accountUser(payload);
          authRedirectingRef.current = false;
          setUser(nextUser);
          const nextAuthorization = accountAuthorization(payload);
          setAuthorization(nextAuthorization);
          if (nextUser.id) {
            const nextVersion = Number(nextAuthorization?.authzVersion ?? 1);
            const previousNamespace = window.sessionStorage.getItem('shuku:session:authz-namespace');
            const nextNamespace = `${nextUser.id}:${nextVersion}`;
            if (previousNamespace && previousNamespace !== nextNamespace) {
              void clearPrivatePwaStorage().catch(() => undefined);
            }
            setCurrentUserNamespace(nextUser.id, nextVersion);
            if (nextUser.locale === 'zh-CN' || nextUser.locale === 'en-US') {
              window.localStorage.setItem(userDevicePreferenceKey('shuku.locale', nextUser.id), nextUser.locale);
              setLocale(nextUser.locale);
            }
            navigator.serviceWorker?.controller?.postMessage({
              type: 'SET_PRIVATE_CACHE_NAMESPACE',
              userId: nextUser.id,
              authzVersion: nextVersion
            });
          }
          setSessionStatus('authenticated');
        } else {
          // A network/proxy/server failure is not proof that the user signed out.
          // Let the page's normal error and offline handling remain available.
          setSessionStatus('unavailable');
        }
      })
      .catch((reason) => {
        if (active && !(reason instanceof DOMException && reason.name === 'AbortError')) {
          setSessionStatus('unavailable');
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [isProtectedPage, pathname, redirectToLogin, setLocale]);

  useEffect(() => {
    if (pathname !== '/login') return undefined;
    let active = true;
    const controller = new AbortController();
    apiV2Fetch('/api/v2/account', {
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null) as AccountResponse | null;
        if (!active) return;
        if (response.ok && payload?.id) {
          router.replace(safePostLoginPath(new URLSearchParams(currentSearchString).get('next')));
        } else if (response.status === 401) {
          void clearPrivatePwaStorage().catch(() => undefined);
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
      controller.abort();
    };
  }, [currentSearchString, pathname, router]);

  useEffect(() => {
    const showingReaderGate = isReader && (sessionStatus === 'checking' || sessionStatus === 'redirecting');
    if (!shellSurface || (isReader && !showingReaderGate)) return undefined;

    const previousHtmlBackground = document.documentElement.style.backgroundColor;
    const previousBodyBackground = document.body.style.backgroundColor;
    const previousColorScheme = document.documentElement.style.colorScheme;
    const foundThemeColorMetas = Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'));
    const createdThemeColor = foundThemeColorMetas.length === 0 ? ensureMeta('theme-color') : null;
    const themeColorMetas = createdThemeColor ? [createdThemeColor.meta] : foundThemeColorMetas;
    const { meta: statusBarMeta, created: createdStatusBarMeta } = ensureMeta('apple-mobile-web-app-status-bar-style');
    const previousThemeColors = themeColorMetas.map((meta) => meta.content);
    const previousStatusBarStyle = statusBarMeta.content;

    function applySurface() {
      document.documentElement.style.backgroundColor = shellSurface.background;
      document.body.style.backgroundColor = shellSurface.background;
      document.documentElement.style.colorScheme = shellSurface.colorScheme;
      const currentThemeColorMetas = Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'));
      const targetThemeColorMetas = currentThemeColorMetas.length > 0 ? currentThemeColorMetas : [ensureMeta('theme-color').meta];
      targetThemeColorMetas.forEach((meta) => {
        if (meta.getAttribute('content') !== shellSurface.background) meta.setAttribute('content', shellSurface.background);
      });
      const currentStatusBarMeta = ensureMeta('apple-mobile-web-app-status-bar-style').meta;
      if (currentStatusBarMeta.getAttribute('content') !== shellSurface.statusBarStyle) {
        currentStatusBarMeta.setAttribute('content', shellSurface.statusBarStyle);
      }
    }

    applySurface();
    const frame = window.requestAnimationFrame(applySurface);
    const settleTimer = window.setTimeout(applySurface, 250);
    const syncTimer = window.setInterval(applySurface, 500);
    const headObserver = new MutationObserver(applySurface);
    headObserver.observe(document.head, { attributes: true, childList: true, subtree: true, attributeFilter: ['content'] });

    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(settleTimer);
      window.clearInterval(syncTimer);
      headObserver.disconnect();
      document.documentElement.style.backgroundColor = previousHtmlBackground;
      document.body.style.backgroundColor = previousBodyBackground;
      document.documentElement.style.colorScheme = previousColorScheme;
      themeColorMetas.forEach((meta, index) => {
        if (createdThemeColor?.meta === meta) meta.remove();
        else meta.setAttribute('content', previousThemeColors[index]);
      });
      if (createdStatusBarMeta) statusBarMeta.remove();
      else statusBarMeta.setAttribute('content', previousStatusBarStyle);
    };
  }, [isReader, sessionStatus, shellSurface]);

  useEffect(() => {
    if (isReader || isAuthPage || isOffline || sessionStatus === 'checking' || sessionStatus === 'redirecting') return;
    let active = true;
    const refreshShelves = () => {
      apiV2Fetch('/api/v2/catalog/shelves')
        .then((response) => response.json() as Promise<Page_ShelfResponse_>)
        .then((payload) => {
          if (active) setShelves(payload.items.map(({ id, name }) => ({ id, name })));
        })
        .catch(() => undefined);
    };
    apiV2Fetch('/api/v2/catalog/shelves').then((response) => response.json() as Promise<Page_ShelfResponse_>).catch(() => null).then((shelvesPayload) => {
      if (!active) return;
      setShelves(shelvesPayload?.items.map(({ id, name }) => ({ id, name })) ?? []);
    });
    window.addEventListener('shuku:shelves-changed', refreshShelves);
    const refreshAccount = () => {
      apiV2Fetch('/api/v2/account')
        .then((response) => response.json())
        .then((payload: AccountResponse) => {
          if (active && payload.id) setUser(accountUser(payload));
          if (active && payload.id) setAuthorization(accountAuthorization(payload));
        })
        .catch(() => undefined);
    };
    window.addEventListener('shuku:account-changed', refreshAccount);
    return () => {
      active = false;
      window.removeEventListener('shuku:shelves-changed', refreshShelves);
      window.removeEventListener('shuku:account-changed', refreshAccount);
    };
  }, [isAuthPage, isOffline, isReader, pathname, sessionStatus]);

  useEffect(() => {
    setSearchFocused(false);
  }, [currentSearchString, pathname]);

  useEffect(() => {
    setAvatarFailed(false);
  }, [user?.avatarUrl]);

  useEffect(() => {
    function handleHistoryChange() {
      if (!drawerHistoryEntryRef.current && !drawerOpenRef.current) return;
      drawerHistoryEntryRef.current = false;
      const pendingNavigation = drawerPendingNavigationRef.current;
      drawerPendingNavigationRef.current = null;
      finishClosingMobileDrawer(!pendingNavigation && restoreDrawerTriggerFocusRef.current);
      if (pendingNavigation) {
        window.requestAnimationFrame(() => router.push(pendingNavigation));
      }
    }

    window.addEventListener('popstate', handleHistoryChange);
    return () => window.removeEventListener('popstate', handleHistoryChange);
  }, [finishClosingMobileDrawer, router]);

  useEffect(() => {
    if (!mobileDrawerOpen) return undefined;
    const previousBodyOverflow = document.body.style.overflow;
    const previousHtmlOverscroll = document.documentElement.style.overscrollBehavior;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overscrollBehavior = 'none';
    const mainElement = appMainRef.current;
    mainElement?.setAttribute('inert', '');

    const focusFrame = window.requestAnimationFrame(() => {
      const focusSearch = focusMobileSearchOnOpenRef.current;
      focusMobileSearchOnOpenRef.current = false;
      if (focusSearch) mobileSearchInputRef.current?.focus();
      else drawerCloseButtonRef.current?.focus();
    });

    function handleDrawerKeyboard(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeMobileDrawer(true);
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(drawerPanelRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ) ?? []).filter((element) => !element.hasAttribute('hidden'));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleDrawerKeyboard);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener('keydown', handleDrawerKeyboard);
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.overscrollBehavior = previousHtmlOverscroll;
      mainElement?.removeAttribute('inert');
      if (restoreDrawerTriggerFocusRef.current) {
        window.requestAnimationFrame(() => drawerTriggerRef.current?.focus());
      }
    };
  }, [closeMobileDrawer, mobileDrawerOpen]);

  useEffect(() => {
    const desktopQuery = window.matchMedia('(min-width: 1024px)');
    function closeAfterDesktopTransition(event: MediaQueryListEvent) {
      if (event.matches && drawerOpenRef.current) closeMobileDrawer(false);
    }
    desktopQuery.addEventListener('change', closeAfterDesktopTransition);
    return () => desktopQuery.removeEventListener('change', closeAfterDesktopTransition);
  }, [closeMobileDrawer]);

  useEffect(() => {
    if (!searchFocused) return;
    function closeOnOutsideClick(event: MouseEvent) {
      if (!searchFormRef.current?.contains(event.target as Node)) setSearchFocused(false);
    }
    window.addEventListener('mousedown', closeOnOutsideClick);
    return () => window.removeEventListener('mousedown', closeOnOutsideClick);
  }, [searchFocused]);

  useEffect(() => {
    if (isReader || isAuthPage || isOffline) return;
    function focusSearch(event: globalThis.KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        if (window.matchMedia('(max-width: 1023px)').matches) {
          if (drawerOpenRef.current) {
            mobileSearchInputRef.current?.focus();
          } else {
            const trigger = document.querySelector<HTMLButtonElement>(`button[aria-controls="${MOBILE_NAVIGATION_DRAWER_ID}"]`);
            focusMobileSearchOnOpenRef.current = true;
            if (trigger) openMobileDrawer(trigger);
          }
        } else {
          searchInputRef.current?.focus();
          setSearchFocused(true);
        }
      }
    }
    window.addEventListener('keydown', focusSearch);
    return () => window.removeEventListener('keydown', focusSearch);
  }, [isAuthPage, isOffline, isReader, openMobileDrawer]);

  useEffect(() => {
    const keyword = librarySearch.trim();
    if (!keyword) {
      setSearchBooks([]);
      setSearchTotal(0);
      setSearchLoading(false);
      setSearchActiveIndex(0);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearchLoading(true);
      apiV2Fetch(`/api/v2/catalog/works?pageSize=5&visibility=active&query=${encodeURIComponent(keyword)}`, { signal: controller.signal })
        .then((response) => response.json() as Promise<Page_WorkResponse_>)
        .then((payload) => {
          setSearchBooks(payload.items.map((work) => ({
            id: work.id,
            title: work.title,
            author: work.author ?? '',
            coverUrl: '',
            format: work.mediaType
          })));
          setSearchTotal(payload.total);
          setSearchActiveIndex(0);
        })
        .catch((reason) => {
          if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
            setSearchBooks([]);
            setSearchTotal(0);
            toast.error('搜索书库失败', reason instanceof Error ? reason.message : '请稍后重试');
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setSearchLoading(false);
        });
    }, 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [librarySearch, toast]);

  function openLibrarySearch() {
    const keyword = librarySearch.trim();
    if (!keyword) return;
    setSearchFocused(false);
    router.push(`/library?search=${encodeURIComponent(keyword)}`);
  }

  function submitLibrarySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (searchFocused) {
      const selectedBook = searchBooks[searchActiveIndex];
      if (selectedBook) {
        setSearchFocused(false);
        router.push(`/works/${selectedBook.id}`);
        return;
      }
    }
    openLibrarySearch();
  }

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!librarySearch.trim()) return;
    const optionCount = searchBooks.length + 1;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      setSearchFocused(true);
      setSearchActiveIndex((current) => (current + (event.key === 'ArrowDown' ? 1 : -1) + optionCount) % optionCount);
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      setSearchFocused(false);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const selectedBook = searchBooks[searchActiveIndex];
      if (searchFocused && selectedBook) {
        setSearchFocused(false);
        router.push(`/works/${selectedBook.id}`);
      } else {
        openLibrarySearch();
      }
    }
  }

  function submitMobileDrawerSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const keyword = librarySearch.trim();
    if (!keyword) {
      mobileSearchInputRef.current?.focus();
      return;
    }
    navigateFromMobileDrawer(`/library?search=${encodeURIComponent(keyword)}`);
  }

  function handleDrawerPointerDown(event: ReactPointerEvent<HTMLElement>) {
    if (!event.isPrimary) return;
    drawerSwipeStartRef.current = { x: event.clientX, y: event.clientY };
  }

  function handleDrawerPointerUp(event: ReactPointerEvent<HTMLElement>) {
    const start = drawerSwipeStartRef.current;
    drawerSwipeStartRef.current = null;
    if (!start || !event.isPrimary) return;
    const horizontalDistance = event.clientX - start.x;
    const verticalDistance = event.clientY - start.y;
    if (horizontalDistance < -56 && Math.abs(horizontalDistance) > Math.abs(verticalDistance) * 1.2) {
      closeMobileDrawer(true);
    }
  }

  if (isProtectedPage && (sessionStatus === 'checking' || sessionStatus === 'redirecting')) {
    return (
      <div
        className="flex min-h-[100dvh] items-center justify-center px-6 text-sm text-[#77736F]"
        style={{ backgroundColor: shellSurface.background }}
        role="status"
        aria-live="polite"
      >
        <I18nText>正在验证登录状态...</I18nText></div>
    );
  }

  if (isReader || isAuthPage || isOffline) {
    return (
      <>
        {children}
        <PwaClient />
      </>
    );
  }

  return (
    <MobileNavigationProvider open={mobileDrawerOpen} openDrawer={openMobileDrawer}>
    <div className="shuku-app-shell min-h-screen bg-[var(--shuku-bg)] text-[var(--shuku-text)] [--shuku-sidebar-width:clamp(236px,16vw,264px)]">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-[var(--shuku-sidebar-width)] flex-col border-r border-black/[0.04] bg-[#F3F0EC]/95 px-4 pb-5 pt-7 backdrop-blur-xl lg:flex">
        <Link href="/" className="flex shrink-0 items-center gap-3 px-3">
          <span className="h-9 w-9 overflow-hidden rounded-[9px] bg-[#F7F1E8] shadow-sm">
            <Image src={withBasePath('/icons/icon-192.png')} alt="" width={36} height={36} className="h-full w-full object-cover" priority />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-[18px] font-semibold tracking-tight">{PRODUCT_NAME}</span>
          </span>
        </Link>

        {isSettingsMode ? (
          <nav aria-label={i18nAttribute("返回主导航")} className="mt-8 space-y-1">
            <Link
              href="/"
              className="flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] font-medium text-[#34312E] transition hover:bg-black/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
            >
              <ArrowLeft size={20} strokeWidth={1.75} />
              <I18nText>返回阅读</I18nText></Link>
          </nav>
        ) : null}

        {!isSettingsMode ? <form ref={searchFormRef} onSubmit={submitLibrarySearch} className="relative mt-8">
          <div className="flex h-11 items-center gap-2.5 rounded-xl bg-black/[0.045] px-3 text-[#77736F] transition focus-within:bg-white focus-within:shadow-sm">
            <Search size={17} className="shrink-0" strokeWidth={1.8} />
            <input
              ref={searchInputRef}
              value={librarySearch}
              onFocus={() => setSearchFocused(true)}
              onChange={(event) => {
                setLibrarySearch(event.target.value);
                setSearchFocused(true);
              }}
              onKeyDown={handleSearchKeyDown}
              className="min-w-0 flex-1 bg-transparent text-sm text-[#2A2927] outline-none placeholder:text-[#8C8883]"
              placeholder={i18nAttribute("搜索图书")}
              aria-label={i18nAttribute("搜索本地书库")}
              autoComplete="off"
              data-testid="top-search-input"
            />
            <kbd className="shrink-0 text-[11px] text-[#9A9691]">⌘K</kbd>
          </div>
          {searchFocused && librarySearch.trim() ? (
            <div data-testid="top-search-dropdown" className="absolute left-0 top-[calc(100%+8px)] z-40 w-[420px] overflow-hidden rounded-2xl border border-black/[0.07] bg-white shadow-[0_18px_55px_rgba(53,43,35,0.16)]">
              <div className="max-h-[360px] overflow-y-auto py-2">
                {searchLoading ? <div className="px-4 py-5 text-sm text-[#77736F]"><I18nText>正在搜索书库...</I18nText></div> : null}
                {!searchLoading && searchBooks.map((book, index) => (
                  <button
                    key={book.id}
                    type="button"
                    data-testid="top-search-book-result"
                    aria-current={searchActiveIndex === index ? 'true' : undefined}
                    onMouseEnter={() => setSearchActiveIndex(index)}
                    onClick={() => {
                      setSearchFocused(false);
                      router.push(`/works/${book.id}`);
                    }}
                    className={cn(
                      'flex w-full items-center gap-3 px-3 py-2.5 text-left outline-none transition',
                      searchActiveIndex === index ? 'bg-[#FDE9E2]' : 'hover:bg-[#F7F4F0] focus:bg-[#F7F4F0]'
                    )}
                  >
                    <Cover book={book} size="small" className="h-14 w-10 shrink-0 rounded-md shadow-sm" small />
                    <span data-i18n-skip className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-[#252321]">{book.title}</span>
                      <span className="mt-1 block truncate text-xs text-[#817C76]">{book.author} · {book.format}</span>
                    </span>
                  </button>
                ))}
                {!searchLoading && searchBooks.length === 0 ? <div className="px-4 py-5 text-sm text-[#77736F]"><I18nText>书库中没有匹配读物</I18nText></div> : null}
              </div>
              <button
                type="button"
                data-testid="top-search-all-results"
                aria-current={searchActiveIndex === searchBooks.length ? 'true' : undefined}
                onMouseEnter={() => setSearchActiveIndex(searchBooks.length)}
                onClick={openLibrarySearch}
                className={cn(
                  'flex w-full items-center justify-between gap-3 border-t border-black/[0.06] px-4 py-3 text-left text-sm font-medium text-[#EF4D2F] outline-none transition',
                  searchActiveIndex === searchBooks.length ? 'bg-[#FDE9E2]' : 'bg-white hover:bg-[#FFF5F1] focus:bg-[#FFF5F1]'
                )}
              >
                <span className="truncate">{i18nAttribute('查看“{value0}”的全部结果', { value0: librarySearch.trim() })}</span>
                <span className="shrink-0 text-xs text-[#A29D97]">{searchTotal} <I18nText>本</I18nText></span>
              </button>
            </div>
          ) : null}
        </form> : null}

        <div className="mt-6 min-h-0 flex-1 overflow-y-auto pr-1">
          {isSettingsMode ? (
            <section>
              <nav aria-label={i18nAttribute("设置分类")} className="space-y-5">
                {settingsGroups.map((group) => {
                  const items = group.items.filter((item) => settingsItemAllowed(item.access, authorization));
                  if (!items.length) return null;
                  return (
                    <section key={group.key} aria-label={group.label ? i18nAttribute(group.label) : undefined}>
                      {group.label ? <div className="mb-2 px-3 text-xs font-semibold tracking-[0.08em] text-[#938D86]">{i18nAttribute(group.label)}</div> : null}
                      <div className="space-y-1">
                        {items.map(({ href, icon: Icon, label }) => {
                          const active = isSettingsItemActive(pathname, href);
                          return (
                            <Link
                              key={href}
                              href={href}
                              aria-current={active ? 'page' : undefined}
                              className={cn(
                                'flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]',
                                active ? 'bg-[#F9DED4] text-[#EF4D2F]' : 'text-[#34312E] hover:bg-black/[0.04]'
                              )}
                            >
                              <Icon size={20} strokeWidth={1.75} />
                              <span className="truncate">{i18nAttribute(label)}</span>
                            </Link>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </nav>
            </section>
          ) : <><nav className="space-y-1">
            {primaryNavItems.map(({ href, icon: Icon, label }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  'flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] font-medium transition',
                  isActive(pathname, currentSearch, href) ? 'bg-[#F9DED4] text-[#EF4D2F]' : 'text-[#34312E] hover:bg-black/[0.04]'
                )}
              >
                <Icon size={20} strokeWidth={1.8} />
                {i18nAttribute(label)}
              </Link>
            ))}
          </nav>

          <section className="mt-7">
            <div className="mb-2 px-3 text-[13px] text-[#8A857F]"><I18nText>书库</I18nText></div>
            <nav className="space-y-1">
              {libraryNavItems.map(({ href, icon: Icon, label }) => (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    'flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] font-medium transition',
                    isActive(pathname, currentSearch, href) ? 'bg-[#F9DED4] text-[#EF4D2F]' : 'text-[#34312E] hover:bg-black/[0.04]'
                  )}
                >
                  <Icon size={20} strokeWidth={1.75} />
                  {i18nAttribute(label)}
                </Link>
              ))}
            </nav>
          </section>

          <section className="mt-7">
            <div className="mb-2 px-3 text-[13px] text-[#8A857F]"><I18nText>我的书架</I18nText></div>
            <nav className="space-y-1">
              {shelves.map((shelf) => {
                const href = `/shelves?shelf=${encodeURIComponent(shelf.id)}`;
                return (
                  <Link
                    key={shelf.id}
                    href={href}
                    className={cn(
                      'flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] font-medium transition',
                      isActive(pathname, currentSearch, href) ? 'bg-[#F9DED4] text-[#EF4D2F]' : 'text-[#34312E] hover:bg-black/[0.04]'
                    )}
                  >
                    <BookOpen size={20} strokeWidth={1.65} />
                    <span data-i18n-skip className="truncate">{shelf.name}</span>
                  </Link>
                );
              })}
              <Link
                href="/shelves?create=1"
                className={cn(
                  'flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] transition',
                  isActive(pathname, currentSearch, '/shelves?create=1') ? 'bg-[#F9DED4] text-[#EF4D2F]' : 'text-[#77736F] hover:bg-black/[0.04]'
                )}
              >
                <Plus size={20} strokeWidth={1.7} />
                <I18nText>新建书架</I18nText></Link>
            </nav>
          </section></>}
        </div>

        <Link
          href="/settings"
          aria-label={i18nAttribute("进入账户与设置")}
          title={user?.email || i18nAttribute("账户与设置")}
          className={cn(
            'mt-3 flex min-h-[72px] w-full shrink-0 items-center gap-3 border-t border-black/[0.07] px-1 pt-3 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]',
            pathname.startsWith('/settings') ? 'text-[#D94A2E]' : 'text-[#302D29]'
          )}
        >
          <Image
            key={user?.avatarUrl && !avatarFailed ? user.avatarUrl : DEFAULT_ACCOUNT_AVATAR_PATH}
            src={withBasePath(user?.avatarUrl && !avatarFailed ? user.avatarUrl : DEFAULT_ACCOUNT_AVATAR_PATH)}
            width={46}
            height={46}
            alt={i18nAttribute("账户头像")}
            priority
            unoptimized={Boolean(user?.avatarUrl && !avatarFailed)}
            onError={() => setAvatarFailed(true)}
            className="h-[46px] w-[46px] shrink-0 rounded-full object-cover shadow-sm"
          />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{user?.name || i18nAttribute("二毛")}</span>
            <span className="mt-0.5 block truncate text-xs text-[#8A847E]"><I18nText>账户与设置</I18nText></span>
          </span>
          <ChevronRight size={20} strokeWidth={1.7} className="shrink-0 text-[#77716B]" aria-hidden="true" />
        </Link>
      </aside>

      <main
        ref={appMainRef}
        data-testid="app-shell-main"
        data-audio-mini-player={audioPlayback.bootstrap || audioPlayback.pendingEditionId ? 'true' : undefined}
        className="shuku-mobile-shell-main min-h-screen pb-8 lg:pl-[var(--shuku-sidebar-width)] lg:pb-0"
      >
        <div data-testid="app-shell-content" className="shuku-mobile-shell-content px-5 py-7 sm:px-7 lg:px-10 lg:py-10 xl:px-12 xl:py-12">{children}</div>
      </main>

      <div
        className="shuku-mobile-drawer-root fixed inset-0 z-[100] lg:hidden"
        data-open={mobileDrawerOpen ? 'true' : 'false'}
        aria-hidden={!mobileDrawerOpen}
      >
        <button
          type="button"
          className="shuku-mobile-drawer-scrim absolute inset-0 bg-[#241F1C]/45 backdrop-blur-[1.5px]"
          onClick={() => closeMobileDrawer(true)}
          aria-label={i18nAttribute("关闭导航菜单")}
          tabIndex={mobileDrawerOpen ? 0 : -1}
        />
        <aside
          ref={drawerPanelRef}
          id={MOBILE_NAVIGATION_DRAWER_ID}
          data-testid="mobile-navigation"
          className="shuku-mobile-drawer-panel absolute inset-y-0 left-0 flex w-[min(82vw,320px)] touch-pan-y flex-col border-r border-black/[0.055] bg-[#F3F0EC] px-4 shadow-[22px_0_60px_rgba(41,31,25,0.20)]"
          role="dialog"
          aria-modal="true"
          aria-label={i18nAttribute("主导航")}
          onPointerDown={handleDrawerPointerDown}
          onPointerUp={handleDrawerPointerUp}
          onPointerCancel={() => { drawerSwipeStartRef.current = null; }}
        >
          <header className="flex shrink-0 items-center gap-3 px-1">
            <span className="h-11 w-11 shrink-0 overflow-hidden rounded-[11px] bg-[#F7F1E8] shadow-sm">
              <Image src={withBasePath('/icons/icon-192.png')} alt="" width={44} height={44} className="h-full w-full object-cover" priority />
            </span>
            <span className="min-w-0 flex-1 truncate text-[18px] font-semibold tracking-[-0.02em] text-[#292724]">{PRODUCT_NAME}</span>
            <button
              ref={drawerCloseButtonRef}
              type="button"
              onClick={() => closeMobileDrawer(true)}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] border border-black/[0.075] bg-white/45 text-[#5D5751] transition duration-200 hover:bg-white/80 hover:text-[#272421] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
              aria-label={i18nAttribute("关闭导航菜单")}
            >
              <X size={22} strokeWidth={1.7} aria-hidden="true" />
            </button>
          </header>

          <form onSubmit={submitMobileDrawerSearch} className="mt-6 shrink-0">
            <label className="flex min-h-12 items-center gap-3 rounded-[14px] border border-black/[0.075] bg-white/45 px-3.5 text-[#77716B] transition focus-within:border-[#F0AA96] focus-within:bg-white focus-within:ring-2 focus-within:ring-[#F8D3C7]">
              <Search size={19} strokeWidth={1.75} className="shrink-0" aria-hidden="true" />
              <input
                ref={mobileSearchInputRef}
                value={librarySearch}
                onChange={(event) => setLibrarySearch(event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-[15px] text-[#2A2927] outline-none placeholder:text-[#8C8883]"
                placeholder={i18nAttribute("搜索图书")}
                aria-label={i18nAttribute("搜索图书")}
                autoComplete="off"
              />
            </label>
          </form>

          <div className="mt-5 min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1">
            <nav aria-label={i18nAttribute("主要页面")} className="space-y-1">
              {primaryNavItems.map(({ href, icon: Icon, label }) => (
                <Link
                  key={`${href}-drawer`}
                  href={href}
                  onClick={(event) => handleMobileDrawerLink(event, href)}
                  aria-current={isActive(pathname, currentSearch, href) ? 'page' : undefined}
                  className={cn(
                    'flex min-h-12 items-center gap-3 rounded-[14px] px-3.5 text-[15px] font-medium transition duration-200 active:scale-[0.985] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]',
                    isActive(pathname, currentSearch, href) ? 'bg-[#F9DED4] text-[#E94B2D]' : 'text-[#34312E] hover:bg-black/[0.045]'
                  )}
                >
                  <Icon size={21} strokeWidth={1.75} aria-hidden="true" />
                  {i18nAttribute(label)}
                </Link>
              ))}
            </nav>

            <section className="mt-6">
              <div className="mb-2 px-3.5 text-[13px] font-medium text-[#8A857F]"><I18nText>书库</I18nText></div>
              <nav aria-label={i18nAttribute("书库")} className="space-y-1">
                {libraryNavItems.map(({ href, icon: Icon, label }) => (
                  <Link
                    key={`${href}-drawer`}
                    href={href}
                    onClick={(event) => handleMobileDrawerLink(event, href)}
                    aria-current={isActive(pathname, currentSearch, href) ? 'page' : undefined}
                    className={cn(
                      'flex min-h-12 items-center gap-3 rounded-[14px] px-3.5 text-[15px] font-medium transition duration-200 active:scale-[0.985] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]',
                      isActive(pathname, currentSearch, href) ? 'bg-[#F9DED4] text-[#E94B2D]' : 'text-[#34312E] hover:bg-black/[0.045]'
                    )}
                  >
                    <Icon size={21} strokeWidth={1.75} aria-hidden="true" />
                    {i18nAttribute(label)}
                  </Link>
                ))}
              </nav>
            </section>

            <section className="mt-6 border-t border-black/[0.065] pt-5">
              <div className="mb-2 px-3.5 text-[13px] font-medium text-[#8A857F]"><I18nText>我的书架</I18nText></div>
              <nav aria-label={i18nAttribute("我的书架")} className="space-y-1">
                {shelves.map((shelf) => {
                  const href = `/shelves?shelf=${encodeURIComponent(shelf.id)}`;
                  return (
                    <Link
                      key={`${shelf.id}-drawer`}
                      href={href}
                      onClick={(event) => handleMobileDrawerLink(event, href)}
                      aria-current={isActive(pathname, currentSearch, href) ? 'page' : undefined}
                      className={cn(
                        'flex min-h-12 items-center gap-3 rounded-[14px] px-3.5 text-[15px] font-medium transition duration-200 active:scale-[0.985] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]',
                        isActive(pathname, currentSearch, href) ? 'bg-[#F9DED4] text-[#E94B2D]' : 'text-[#34312E] hover:bg-black/[0.045]'
                      )}
                    >
                      <BookOpen size={21} strokeWidth={1.7} aria-hidden="true" />
                      <span data-i18n-skip className="truncate">{shelf.name}</span>
                    </Link>
                  );
                })}
                <Link
                  href="/shelves?create=1"
                  onClick={(event) => handleMobileDrawerLink(event, '/shelves?create=1')}
                  className="flex min-h-12 items-center gap-3 rounded-[14px] px-3.5 text-[15px] text-[#69635D] transition duration-200 hover:bg-black/[0.045] active:scale-[0.985] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
                >
                  <Plus size={21} strokeWidth={1.75} aria-hidden="true" />
                  <I18nText>新建书架</I18nText></Link>
              </nav>
            </section>
          </div>

          <Link
            href="/settings"
            onClick={(event) => handleMobileDrawerLink(event, '/settings')}
            aria-current={pathname.startsWith('/settings') ? 'page' : undefined}
            className={cn(
              'mt-3 flex min-h-[72px] shrink-0 items-center gap-3 border-t border-black/[0.07] px-1 pt-3 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]',
              pathname.startsWith('/settings') ? 'text-[#D94A2E]' : 'text-[#302D29]'
            )}
          >
            <Image
              key={user?.avatarUrl && !avatarFailed ? user.avatarUrl : DEFAULT_ACCOUNT_AVATAR_PATH}
              src={withBasePath(user?.avatarUrl && !avatarFailed ? user.avatarUrl : DEFAULT_ACCOUNT_AVATAR_PATH)}
              width={46}
              height={46}
              alt={i18nAttribute("账户头像")}
              unoptimized={Boolean(user?.avatarUrl && !avatarFailed)}
              onError={() => setAvatarFailed(true)}
              className="h-[46px] w-[46px] shrink-0 rounded-full object-cover shadow-sm"
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">{user?.name || i18nAttribute("二毛")}</span>
              <span className="mt-0.5 block truncate text-xs text-[#8A847E]"><I18nText>账户与设置</I18nText></span>
            </span>
            <ChevronRight size={20} strokeWidth={1.7} className="shrink-0 text-[#77716B]" aria-hidden="true" />
          </Link>
        </aside>
      </div>
      <PwaClient />
    </div>
    </MobileNavigationProvider>
  );
}
