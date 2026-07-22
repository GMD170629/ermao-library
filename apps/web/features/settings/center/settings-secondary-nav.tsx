'use client';

import { Database, FileText, Mail, Settings, Sparkles } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '../../../components/ui/cn';

export const settingsItems = [
  { href: '/settings', label: '通用', icon: Settings },
  { href: '/settings/library', label: '书库来源与导入', icon: Database },
  { href: '/settings/organize', label: '智能整理', icon: Sparkles },
  { href: '/settings/email', label: '邮件与 Kindle', icon: Mail },
  { href: '/settings/data', label: '数据与系统', icon: Database },
  { href: '/settings/logs', label: '系统日志', icon: FileText }
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
                'flex min-h-12 min-w-0 items-center gap-2 rounded-2xl px-3 py-3 text-[13px] font-medium transition focus:outline-none focus:ring-4 focus:ring-[#FAD9D0] sm:gap-3 sm:px-4 sm:text-sm',
                active ? 'bg-[#FCE5DE] text-[#ED4D2D]' : 'text-[#4F4B46] hover:bg-[#F3F0EC] hover:text-[#242220]'
              )}
            >
              <Icon size={18} className="shrink-0" strokeWidth={1.8} />
              <span className="whitespace-nowrap">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
