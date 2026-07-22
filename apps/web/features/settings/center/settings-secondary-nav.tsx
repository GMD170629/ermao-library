'use client';

import { Database, FileText, Info, Mail, Settings, Sparkles } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '../../../components/ui/cn';

export const settingsItems = [
  { href: '/settings', label: '通用', icon: Settings },
  { href: '/settings/library', label: '书库来源与导入', icon: Database },
  { href: '/settings/organize', label: '智能整理', icon: Sparkles },
  { href: '/settings/email', label: '邮件与 Kindle', icon: Mail },
  { href: '/settings/data', label: '数据与系统', icon: Database },
  { href: '/settings/logs', label: '系统日志', icon: FileText },
  { href: '/settings/about', label: '关于', icon: Info }
];

export function isSettingsItemActive(pathname: string, href: string) {
  return href === '/settings' ? pathname === href : pathname.startsWith(href);
}

export function SettingsSecondaryNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="设置分类" className="border-b border-[#DEDAD4] pb-5 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-7">
      <div className="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1">
        {settingsItems.map(({ href, label, icon: Icon }) => {
          const active = isSettingsItemActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'flex min-h-11 min-w-0 items-center gap-2 rounded-xl px-3 text-[13px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5] sm:gap-3 sm:text-[15px]',
                active ? 'bg-[#F9DED4] text-[#EF4D2F]' : 'text-[#34312E] hover:bg-black/[0.04]'
              )}
            >
              <Icon size={20} className="shrink-0" strokeWidth={1.75} />
              <span className="whitespace-nowrap">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
