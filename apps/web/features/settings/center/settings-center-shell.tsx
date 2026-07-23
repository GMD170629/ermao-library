'use client';

import { Plus } from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { I18nText, useI18n } from '../../../i18n/provider';
import { MobileNavigationTrigger } from '../../../components/layout/mobile-navigation';
import { SettingsSecondaryNav } from './settings-secondary-nav';

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
  const { t } = useI18n();
  return (
    <div className="min-h-[calc(100vh-9rem)] rounded-[30px] bg-[#FCFBF9] px-5 py-6 text-[#272522] sm:px-7 lg:px-9 lg:py-8">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3 sm:gap-4">
          <MobileNavigationTrigger />
          <h1 className="truncate text-3xl font-semibold tracking-[-0.035em] text-[#20201F] lg:text-[40px]"><I18nText>设置</I18nText></h1>
        </div>
        <div className="flex items-center gap-2">
          {actions}
          <Link
            href="/library?upload=1"
            aria-label={t('前往上传读物')}
            title={t('上传读物')}
            className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-[#D8D4CE] bg-white text-[#2F2D2A] transition hover:border-[#F05A3C] hover:text-[#F05A3C] focus:outline-none focus:ring-4 focus:ring-[#FAD9D0]"
          >
            <Plus size={22} />
          </Link>
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
