'use client';

import Link from 'next/link';
import { useEffect, useState, type MouseEvent } from 'react';
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
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  useEffect(() => {
    setPendingKey(null);
  }, [active]);

  function beginTabNavigation(event: MouseEvent<HTMLAnchorElement>, key: string) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    setPendingKey(key);
  }

  return (
    <nav aria-label={t('页面分区')} className="flex flex-wrap gap-7 border-b border-[#DEDAD4]">
      {tabs.map((tab) => {
        const selected = pendingKey ? pendingKey === tab.key : active === tab.key;
        const current = active === tab.key;
        return (
          <Link
            key={tab.key}
            href={tab.href}
            onClick={(event) => beginTabNavigation(event, tab.key)}
            aria-current={current ? 'page' : undefined}
            data-pending-navigation={selected && !current ? 'true' : undefined}
            className={cn(
              'relative inline-flex min-h-11 items-center gap-2 pb-3 text-sm font-medium transition focus:outline-none',
              selected ? 'text-[#ED4D2D]' : 'text-[#716B64] hover:text-[#2C2926]'
            )}
          >
            {t(tab.label)}
            {typeof tab.count === 'number' ? <span className="text-xs">{tab.count}</span> : null}
            <span
              aria-hidden="true"
              className={cn(
                'absolute inset-x-0 bottom-[-1px] h-0.5 origin-left rounded-full bg-[#ED4D2D] transition-transform duration-150 ease-out',
                selected ? 'scale-x-100' : 'scale-x-0'
              )}
            />
          </Link>
        );
      })}
    </nav>
  );
}
