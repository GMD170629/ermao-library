'use client';

import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useI18n } from '@/i18n/provider';
import { type StorageCategory } from '../api/storage-client';
import { useStorageManagement } from '../application/use-storage-management';

const categories: Record<StorageCategory, { label: string; color: string }> = {
  program: { label: '程序与依赖', color: 'var(--visual-color-app-brand-accent)' },
  database: { label: '数据库', color: 'var(--visual-color-app-focus-ring)' },
  images: { label: '图片', color: 'var(--visual-color-app-warning)' },
  cache: { label: '缓存', color: 'var(--visual-color-app-success)' },
  logs: { label: '日志', color: 'var(--visual-color-app-text-secondary)' },
  backups: { label: '备份', color: 'var(--visual-color-app-text-tertiary)' },
  updates: { label: '更新文件', color: 'var(--visual-color-app-accent-soft)' },
  uploads: { label: '上传暂存', color: 'var(--visual-color-app-danger-container)' },
  other: { label: '其他', color: 'var(--visual-color-app-divider-strong)' }
};

export function StorageSettingsPanel() {
  const { t, locale } = useI18n();
  const { usage, busy, error, refresh, clear } = useStorageManagement();
  const total = usage?.categories.reduce((sum, row) => sum + row.sizeBytes, 0) ?? 0;
  const size = (bytes: number) => {
    const unit = bytes >= 1024 ** 3 ? 3 : bytes >= 1024 ** 2 ? 2 : bytes >= 1024 ? 1 : 0;
    return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(bytes / 1024 ** unit)} ${['B', 'KB', 'MB', 'GB'][unit]}`;
  };
  const percent = (bytes: number) => new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(total ? bytes / total : 0);

  return <section aria-label={t('空间管理')}>
    <div className="mb-4 flex justify-end"><Button variant="secondary" icon={RefreshCw} loading={busy === 'refresh'} disabled={busy !== null} onClick={refresh}>刷新</Button></div>
    {error ? <p role="alert" className="mb-4 text-sm text-[var(--visual-color-app-danger)]">{t(error)}</p> : null}
    {usage ? <div aria-busy={busy !== null}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--visual-color-app-divider)] pb-5 text-sm">
        <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2"><span className="font-semibold">{t('系统目录')}</span><span className="break-all text-[var(--visual-color-app-text-secondary)]">{usage.root}</span></div>
        <div className="shrink-0"><span className="mr-2 text-[var(--visual-color-app-text-secondary)]">{t('已用')}</span><strong className="text-base tabular-nums">{size(total)}</strong></div>
      </div>
      <div className="my-6 flex h-8 overflow-hidden rounded-xl bg-[var(--visual-color-app-navigation)]" role="img" aria-label={t('系统目录空间组成')}>
        {usage.categories.map((row) => <span key={row.id} style={{ width: `${total ? row.sizeBytes / total * 100 : 0}%`, backgroundColor: categories[row.id].color }} title={`${t(categories[row.id].label)} ${size(row.sizeBytes)} · ${percent(row.sizeBytes)}`} />)}
      </div>
      <ul>
        {usage.categories.map((row) => <li key={row.id} className="grid min-h-[68px] grid-cols-[1fr_auto] items-center gap-x-4 border-b border-[var(--visual-color-app-divider)] py-3 sm:grid-cols-[1fr_7rem_6rem]">
          <div className="flex min-w-0 items-center gap-3"><span className="h-4 w-4 shrink-0 rounded-full" style={{ backgroundColor: categories[row.id].color }} /><span className="font-semibold">{t(categories[row.id].label)}</span><span className="text-sm tabular-nums text-[var(--visual-color-app-text-secondary)]">{percent(row.sizeBytes)}</span></div>
          <span className="text-right text-sm tabular-nums text-[var(--visual-color-app-text-secondary)]">{size(row.sizeBytes)}</span>
          <div className="col-span-2 flex justify-end sm:col-span-1">{row.clearable ? <Button variant="danger" loading={busy === row.id} disabled={busy !== null} aria-label={`${t('清理')} ${t(categories[row.id].label)}`} onClick={() => clear(row.id)}>清理</Button> : null}</div>
        </li>)}
      </ul>
    </div> : busy ? <p role="status" className="text-sm text-[var(--visual-color-app-text-secondary)]">{t('正在统计')}</p> : null}
  </section>;
}
