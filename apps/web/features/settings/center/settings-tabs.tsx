'use client';

import Link from 'next/link';
import { cn } from '../../../components/ui/cn';
import { useI18n } from '../../../i18n/provider';

export type SettingsTab = {
  key: string;
  label: string;
  href: string;
  count?: number;
};

export function SettingsTabs({ tabs, active }: { tabs: SettingsTab[]; active: string }) {
  const { t } = useI18n();
  return (
    <nav aria-label={t('页面分区')} className="flex flex-wrap gap-7 border-b border-[#DEDAD4]">
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          href={tab.href}
          aria-current={active === tab.key ? 'page' : undefined}
          className={cn(
            'relative inline-flex min-h-11 items-center gap-2 pb-3 text-sm font-medium transition focus:outline-none',
            active === tab.key ? 'text-[#ED4D2D]' : 'text-[#716B64] hover:text-[#2C2926]'
          )}
        >
          {t(tab.label)}
          {typeof tab.count === 'number' ? <span className="text-xs">{tab.count}</span> : null}
          {active === tab.key ? <span className="absolute inset-x-0 bottom-[-1px] h-0.5 rounded-full bg-[#ED4D2D]" /> : null}
        </Link>
      ))}
    </nav>
  );
}
