'use client';

import { createContext, useContext, type ReactNode } from 'react';

export type AppSessionUser = {
  id?: string;
  email: string;
  name: string;
  role: string;
  locale?: string;
  avatarUrl?: string | null;
};

export type AppSessionAuthorization = {
  isAdmin: boolean;
  canManageSystem: boolean;
  authzVersion?: number;
};

export type AppSession = {
  user: AppSessionUser | null;
  authorization: AppSessionAuthorization | null;
};

const AppSessionContext = createContext<AppSession | null>(null);
let cachedAppSession: AppSession | null = null;
const SESSION_CACHE_KEY = 'shuku:app-session';

function shouldUsePersistentSessionCache() {
  if (typeof window === 'undefined') return false;
  const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
  return navigation?.type !== 'reload';
}

export function AppSessionProvider({ value, children }: { value: AppSession; children: ReactNode }) {
  return <AppSessionContext.Provider value={value}>{children}</AppSessionContext.Provider>;
}

export function useAppSession() {
  return useContext(AppSessionContext);
}

export function getCachedAppSession() {
  if (cachedAppSession) return cachedAppSession;
  if (typeof window === 'undefined') return null;
  if (!shouldUsePersistentSessionCache()) {
    window.sessionStorage.removeItem(SESSION_CACHE_KEY);
    return null;
  }
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(SESSION_CACHE_KEY) ?? 'null') as AppSession | null;
    if (stored?.user?.email && stored.user.name) cachedAppSession = stored;
  } catch {
    window.sessionStorage.removeItem(SESSION_CACHE_KEY);
  }
  return cachedAppSession;
}

export function setCachedAppSession(session: AppSession) {
  cachedAppSession = session;
  if (typeof window !== 'undefined') window.sessionStorage.setItem(SESSION_CACHE_KEY, JSON.stringify(session));
}

export function clearCachedAppSession() {
  cachedAppSession = null;
  if (typeof window !== 'undefined') window.sessionStorage.removeItem(SESSION_CACHE_KEY);
}
