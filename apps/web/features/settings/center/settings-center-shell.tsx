'use client';

import type { ReactNode } from 'react';
import { I18nText } from '../../../i18n/provider';
import { MobileNavigationTrigger } from '../../../components/layout/mobile-navigation';
import { SettingsSecondaryNav } from './settings-secondary-nav';
import { ReleaseFeedProvider } from '../../updates/public';

export function SettingsCenterShell({
  title,
  description,
  children,
  actions
}: {
  title: string;
  description: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <ReleaseFeedProvider>
      <SettingsCenterContent title={title} description={description} actions={actions}>
        {children}
      </SettingsCenterContent>
    </ReleaseFeedProvider>
  );
}

function SettingsCenterContent({
  title,
  description,
  children,
  actions
}: {
  title: string;
  description: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="min-h-[calc(100vh-9rem)] rounded-[30px] bg-[#FCFBF9] px-5 py-6 text-[#272522] sm:px-7 lg:px-9 lg:py-8">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3 sm:gap-4">
          <MobileNavigationTrigger />
          <h1 className="truncate text-3xl font-semibold tracking-[-0.035em] text-[#20201F] lg:text-[40px]"><I18nText>设置</I18nText></h1>
        </div>
        <div className="flex items-center gap-2">
          {actions}
        </div>
      </div>

      <div className="mt-9">
        <div className="lg:hidden">
          <SettingsSecondaryNav />
        </div>

        <main className="mt-8 min-w-0 lg:mt-0">
          <header className="border-b border-[#DEDAD4] pb-5">
            <h2 className="text-2xl font-semibold tracking-[-0.025em] text-[#20201F] lg:text-[30px]"><I18nText>{title}</I18nText></h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#77716A]"><I18nText>{description}</I18nText></p>
          </header>
          <div className="mt-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
