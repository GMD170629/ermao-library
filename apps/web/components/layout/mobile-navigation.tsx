'use client';

import { Menu } from 'lucide-react';
import { createContext, useContext, type ReactNode } from 'react';
import { cn } from '../ui/cn';

export const MOBILE_NAVIGATION_DRAWER_ID = 'mobile-navigation-drawer';

type MobileNavigationContextValue = {
  open: boolean;
  openDrawer: (trigger: HTMLButtonElement) => void;
};

const MobileNavigationContext = createContext<MobileNavigationContextValue | null>(null);

export function MobileNavigationProvider({
  children,
  open,
  openDrawer
}: MobileNavigationContextValue & { children: ReactNode }) {
  return (
    <MobileNavigationContext.Provider value={{ open, openDrawer }}>
      {children}
    </MobileNavigationContext.Provider>
  );
}

export function MobileNavigationTrigger({ className }: { className?: string }) {
  const navigation = useContext(MobileNavigationContext);
  if (!navigation) return null;

  return (
    <button
      type="button"
      onClick={(event) => navigation.openDrawer(event.currentTarget)}
      className={cn(
        'flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px] border border-black/[0.09] bg-white/55 text-[#302D29] shadow-[0_5px_16px_rgba(64,49,39,0.05)] transition duration-200 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5] lg:hidden',
        navigation.open && 'bg-[#FCE5DE] text-[#D94A2E]',
        className
      )}
      aria-label="打开导航菜单"
      aria-controls={MOBILE_NAVIGATION_DRAWER_ID}
      aria-expanded={navigation.open}
    >
      <Menu size={24} strokeWidth={1.7} aria-hidden="true" />
    </button>
  );
}
