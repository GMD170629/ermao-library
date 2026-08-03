'use client';

import { Activity, BookKey, BookOpen, Database, FileText, Info, Mail, Sparkles, UserRound, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { cn } from '../../../components/ui/cn';
import { useAppSession } from '../../../components/layout/app-session-context';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import rootPackage from '../../../../../package.json';
import { updateStatus, useReleaseFeed } from '../../updates/public';

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
      { href: '/settings/opds', label: 'OPDS', icon: BookKey, access: 'system' },
      { href: '/settings/data', label: '数据和系统', icon: Database, access: 'system' },
      { href: '/settings/health', label: '系统健康检查', icon: Activity, access: 'system' },
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

export function isSettingsItemActive(pathname: string, href: string) {
  return href === '/settings' ? pathname === href : pathname.startsWith(href);
}

export function SettingsSecondaryNav() {
  const { t: i18nAttribute } = useAttributeI18n();
  const { state: releaseFeedState } = useReleaseFeed();
  const pathname = usePathname();
  const router = useRouter();
  const session = useAppSession();
  const authorization = session?.authorization ?? null;
  const [pendingHref, setPendingHref] = useState<string | null>(null);
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
    setPendingHref(null);
    const currentItem = settingsItems.find((item) => isSettingsItemActive(pathname, item.href));
    if (session?.user && currentItem && !settingsItemAllowed(currentItem.access, authorization)) router.replace('/forbidden');
  }, [authorization, pathname, router, session?.user]);

  function beginNavigation(event: MouseEvent<HTMLAnchorElement>, href: string) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    setPendingHref(href);
  }

  return (
    <nav aria-label={i18nAttribute("设置分类")} className="border-b border-[#DEDAD4] pb-5 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-7">
      <div className="space-y-5">
        {visibleGroups.map((group) => (
          <section key={group.key} aria-label={group.label ? i18nAttribute(group.label) : undefined}>
            {group.label ? <div className="mb-2 px-2 text-xs font-semibold tracking-[0.08em] text-[#938D86]">{i18nAttribute(group.label)}</div> : null}
            <div className="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1">
              {group.items.map(({ href, label, icon: Icon }) => {
                const active = isSettingsItemActive(pathname, href);
                const selected = pendingHref ? pendingHref === href : active;
                const hasUpdate = href === '/settings/about'
                  && releaseFeedState.status === 'ready'
                  && updateStatus(rootPackage.version, releaseFeedState.feed).kind === 'update-available';
                return (
                  <Link
                    key={href}
                    href={href}
                    onClick={(event) => beginNavigation(event, href)}
                    aria-current={active ? 'page' : undefined}
                    data-pending-navigation={selected && !active ? 'true' : undefined}
                    className={cn(
                      'flex min-h-11 min-w-0 items-center gap-2 rounded-xl px-3 text-[13px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5] sm:gap-3 sm:text-[15px]',
                      selected ? 'bg-[#F9DED4] text-[#EF4D2F]' : 'text-[#34312E] hover:bg-black/[0.04]'
                    )}
                  >
                    <Icon size={20} className="shrink-0" strokeWidth={1.75} />
                    <span className="whitespace-nowrap">{i18nAttribute(label)}</span>
                    {hasUpdate ? (
                      <>
                        <span className="ml-auto h-2.5 w-2.5 rounded-full bg-[#ED4D2D]" aria-hidden="true" />
                        <span className="sr-only">{i18nAttribute('有新版本')}</span>
                      </>
                    ) : null}
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
