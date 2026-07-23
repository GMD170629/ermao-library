'use client';

import { BookOpen, Database, FileText, Info, Mail, Sparkles, UserRound, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { cn } from '../../../components/ui/cn';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

export type SettingsAccess = 'account' | 'system' | 'admin';
export type SettingsAuthorization = { isAdmin: boolean; canManageSystem: boolean };
export type SettingsItem = { href: string; label: string; icon: LucideIcon; access: SettingsAccess };
export type SettingsGroup = { key: string; label: string | null; items: readonly SettingsItem[] };

export const settingsGroups: readonly SettingsGroup[] = [
  {
    key: 'reader',
    label: '阅读器',
    items: [
      { href: '/settings/reader', label: '当前设备偏好', icon: BookOpen, access: 'account' }
    ]
  },
  {
    key: 'user',
    label: '用户设置',
    items: [
      { href: '/settings', label: '个人信息', icon: UserRound, access: 'account' },
      { href: '/settings/email', label: '邮件与 Kindle', icon: Mail, access: 'account' }
    ]
  },
  {
    key: 'system',
    label: '系统设置',
    items: [
      { href: '/settings/users', label: '用户管理', icon: Users, access: 'admin' },
      { href: '/settings/library', label: '书库来源和导入', icon: Database, access: 'system' },
      { href: '/settings/organize', label: '智能整理', icon: Sparkles, access: 'system' },
      { href: '/settings/data', label: '数据和系统', icon: Database, access: 'system' },
      { href: '/settings/logs', label: '系统日志', icon: FileText, access: 'system' }
    ]
  },
  {
    key: 'about',
    label: null,
    items: [
      { href: '/settings/about', label: '关于', icon: Info, access: 'account' }
    ]
  }
];

export const settingsItems: readonly SettingsItem[] = settingsGroups.flatMap((group) => group.items);

export function settingsItemAllowed(
  access: SettingsAccess,
  authorization: SettingsAuthorization | null | undefined
) {
  if (access === 'account') return true;
  if (access === 'admin') return Boolean(authorization?.isAdmin);
  return Boolean(authorization?.canManageSystem);
}

type AuthorizationPayload = {
  ok?: boolean;
  data?: { authorization?: SettingsAuthorization };
};

export function isSettingsItemActive(pathname: string, href: string) {
  return href === '/settings' ? pathname === href : pathname.startsWith(href);
}

export function SettingsSecondaryNav() {
  const { t: i18nAttribute } = useAttributeI18n();
  const pathname = usePathname();
  const router = useRouter();
  const [authorization, setAuthorization] = useState<SettingsAuthorization | null>(null);
  const visibleGroups = useMemo(
    () => settingsGroups
      .map((group) => ({
        ...group,
        items: group.items.filter((item) => settingsItemAllowed(item.access, authorization))
      }))
      .filter((group) => group.items.length > 0),
    [authorization]
  );

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/auth/me', { cache: 'no-store', credentials: 'same-origin', signal: controller.signal })
      .then((response) => response.json() as Promise<AuthorizationPayload>)
      .then((payload) => {
        const next = payload.ok ? payload.data?.authorization ?? null : null;
        setAuthorization(next);
        const currentItem = settingsItems.find((item) => isSettingsItemActive(pathname, item.href));
        if (currentItem && !settingsItemAllowed(currentItem.access, next)) router.replace('/forbidden');
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [pathname, router]);

  return (
    <nav aria-label={i18nAttribute("设置分类")} className="border-b border-[#DEDAD4] pb-5 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-7">
      <div className="space-y-5">
        {visibleGroups.map((group) => (
          <section key={group.key} aria-label={group.label ? i18nAttribute(group.label) : undefined}>
            {group.label ? <div className="mb-2 px-2 text-xs font-semibold tracking-[0.08em] text-[#938D86]">{i18nAttribute(group.label)}</div> : null}
            <div className="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1">
              {group.items.map(({ href, label, icon: Icon }) => {
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
                    <span className="whitespace-nowrap">{i18nAttribute(label)}</span>
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </nav>
  );
}
