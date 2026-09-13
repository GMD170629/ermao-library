'use client';

import { useI18n } from '@/i18n/provider';

export function DirectoryMountBadge({ path, mountRoot }: { path: string; mountRoot?: string | null }) {
  const { t } = useI18n();
  if (typeof mountRoot !== 'string' || !mountRoot.startsWith('/') || mountRoot === '/') return null;
  const description = t('挂载点：{path}', { path: mountRoot });
  return (
    <span
      title={description}
      aria-label={description}
      className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900"
    >
      {path === mountRoot ? t('挂载目录') : t('挂载目录内')}
    </span>
  );
}
