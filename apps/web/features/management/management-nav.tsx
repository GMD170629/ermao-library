'use client';

import { Activity, LayoutDashboard } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '../../components/ui/cn';
import { useI18n } from '../../i18n/provider';

const items = [
  { href: '/management', label: '概览', icon: LayoutDashboard },
  { href: '/management/logs', label: '日志', icon: Activity }
];

export function ManagementNav() {
  const pathname = usePathname();
  const { t } = useI18n();
  return (
    <nav className="flex flex-wrap gap-2">
      {items.map(({ href, label, icon: Icon }) => {
        const active = href === '/management' ? pathname === href : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              'inline-flex min-h-10 items-center gap-2 rounded-2xl border px-3 text-sm font-medium transition',
              active ? 'border-blue-100 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            )}
          >
            <Icon size={16} />
            {t(label)}
          </Link>
        );
      })}
    </nav>
  );
}
