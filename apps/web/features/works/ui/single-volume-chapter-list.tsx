'use client';

import { BarChart3, CheckCircle2, Circle, LoaderCircle } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import type { VolumeResource } from '../../../types/work';
import { useI18n } from '@/i18n/provider';
import { resolveChapterReadingStates, type ChapterReadingState } from '../chapter-reading-state';
import {
  CHAPTER_DETAIL_PAGE_SIZE,
  detailReaderHref,
  syntheticPdfPageUnits,
  type ChapterDetailUnit,
  type EbookChapterDetail
} from '../model/chapter-detail';

type Props = Readonly<{
  volume: VolumeResource;
  detail: EbookChapterDetail | null;
  loading: boolean;
  error: string;
  requestedPage: number;
  onPageChange: (page: number) => void;
}>;

function pdfState(pageNumber: number, currentPageNumber: number | null, progress: number): ChapterReadingState {
  if (progress >= 100) return 'read';
  if (currentPageNumber === null) return 'unread';
  if (pageNumber === currentPageNumber) return 'current';
  return pageNumber < currentPageNumber ? 'read' : 'unread';
}

export function SingleVolumeChapterList({ volume, detail, loading, error, requestedPage, onPageChange }: Props) {
  const router = useRouter();
  const { t } = useI18n();
  const isPdf = volume.format === 'PDF';
  const pageSize = detail?.page.pageSize ?? CHAPTER_DETAIL_PAGE_SIZE;
  const total = isPdf ? Math.max(0, volume.pageCount ?? detail?.page.total ?? 0) : detail?.page.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.max(1, detail?.page.page ?? requestedPage), totalPages);
  const units = isPdf ? syntheticPdfPageUnits(volume, page, pageSize) : detail?.units ?? [];
  const chapterStates = isPdf
    ? units.map((unit) => pdfState(unit.pageNumber ?? unit.sortOrder + 1, detail?.currentPageNumber ?? null, detail?.progress ?? volume.progress))
    : resolveChapterReadingStates(
      units.map((unit) => ({ href: unit.href ?? undefined, sortOrder: unit.sortOrder })),
      detail?.currentHref,
      detail?.currentChapterSortOrder,
      detail?.progress ?? volume.progress,
      { page, pageSize, total }
    );

  const openReader = () => router.push(`/reader/${encodeURIComponent(volume.id)}`);
  const unitTitle = (unit: ChapterDetailUnit, displayIndex: number) => unit.title || t(isPdf ? '第 {value0} 页' : '第 {value0} 章', { value0: displayIndex });

  return (
    <section className="mt-6" aria-busy={loading || undefined}>
      <div>
        <h2 className="text-lg font-semibold text-stone-950">{t(isPdf ? '页面' : '章节')}</h2>
        <p className="mt-1 text-sm text-stone-500">{t(isPdf ? '共 {value0} 页' : '共 {value0} 章', { value0: total })}</p>
      </div>

      {loading && !detail ? <div className="mt-5 flex min-h-24 items-center justify-center border-y border-stone-100 text-sm text-stone-500" role="status"><LoaderCircle size={18} className="mr-2 animate-spin text-[#ff4f2a]" />{t('正在加载章节…')}</div> : null}

      {!loading && error ? <div className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-red-100 bg-red-50 px-4 py-4 text-sm text-red-700"><span>{error}</span><Button variant="secondary" onClick={openReader}>{t('打开阅读器')}</Button></div> : null}

      {!loading && !error && units.length === 0 ? <div className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-stone-200 px-4 py-4 text-sm text-stone-600"><span>{t(isPdf ? '暂无可定位页面' : '暂无可定位章节')}</span><Button variant="secondary" onClick={openReader}>{t('打开阅读器')}</Button></div> : null}

      {units.length ? <div className={cn('mt-5 divide-y divide-stone-100 border-y border-stone-100 transition-opacity', loading && 'opacity-60')}>
        {units.map((unit, index) => {
          const state = chapterStates[index] ?? 'unread';
          const displayIndex = (page - 1) * pageSize + index + 1;
          const href = detailReaderHref(volume, unit);
          return (
            <button
              key={unit.id}
              type="button"
              disabled={!href}
              onClick={() => href && router.push(href)}
              className={cn('grid min-h-14 w-full grid-cols-[44px_minmax(0,1fr)_72px_24px] items-center gap-3 px-1 text-left text-sm transition hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50 sm:grid-cols-[48px_minmax(0,1fr)_100px_28px]', state === 'current' && 'bg-[#fff4ef] hover:bg-[#fff4ef]')}
            >
              <span className="tabular-nums text-stone-500">{displayIndex}</span>
              <span data-i18n-skip={unit.title ? '' : undefined} className={cn('truncate font-medium', state === 'current' ? 'text-[#e84420]' : 'text-stone-800')}>{unitTitle(unit, displayIndex)}</span>
              <span className={cn('text-xs', state === 'current' ? 'text-[#e84420]' : 'text-stone-400')}>{t(state === 'current' ? '正在阅读' : state === 'read' ? '已读' : '未读')}</span>
              {state === 'current' ? <BarChart3 size={18} className="text-[#ff4f26]" /> : state === 'read' ? <CheckCircle2 size={18} className="text-stone-400" /> : <Circle size={18} className="text-stone-400" />}
            </button>
          );
        })}
      </div> : null}

      {total > 0 && totalPages > 1 ? <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-stone-500">
        <span>{t('第 {value0} / {value1} 页', { value0: page, value1: totalPages })}</span>
        <div className="flex gap-2">
          <Button variant="secondary" className="!min-h-9 !rounded-xl !px-3 !py-1.5" disabled={loading || page <= 1} onClick={() => onPageChange(Math.max(1, page - 1))}>{t('上一页')}</Button>
          <Button variant="secondary" className="!min-h-9 !rounded-xl !px-3 !py-1.5" disabled={loading || page >= totalPages} onClick={() => onPageChange(Math.min(totalPages, page + 1))}>{t('下一页')}</Button>
        </div>
      </div> : null}
    </section>
  );
}
