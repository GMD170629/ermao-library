'use client';

import { AlertTriangle, ArrowLeft, BarChart3, CheckCircle2, Circle, FileImage, Headphones, LoaderCircle } from 'lucide-react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import { useI18n } from '../../../i18n/provider';
import type { ReadableResourceView } from '../../../types/book';
import { formatDuration } from '../book-detail';
import { resolveChapterReadingStates } from '../chapter-reading-state';
import { resourceDetailItemHref, type ResourceDetailPage, type ResourcePageDetailUnit } from '../model/resource-detail';

type Props = Readonly<{
  resource: ReadableResourceView;
  detail: ResourceDetailPage | null;
  loading: boolean;
  error: string;
  requestedPage: number;
  onBack: (() => void) | null;
  onPageChange: (page: number) => void;
}>;

function PreviewTile({ resource, unit }: { resource: ReadableResourceView; unit: ResourcePageDetailUnit }) {
  const router = useRouter();
  const { t } = useI18n();
  const [failed, setFailed] = useState(false);
  const href = resourceDetailItemHref(resource, unit);
  const title = unit.title || t('第 {value0} 页', { value0: unit.pageNumber });

  return <button type="button" disabled={!href} onClick={() => href && router.push(href)} className="group min-w-0 text-left disabled:cursor-not-allowed">
    <span className="relative flex aspect-[3/4] overflow-hidden rounded-xl border border-stone-200 bg-stone-100 shadow-sm transition group-hover:-translate-y-0.5 group-hover:shadow-md group-focus-visible:outline group-focus-visible:outline-2 group-focus-visible:outline-offset-2 group-focus-visible:outline-[#ff4f2a]">
      {unit.previewUrl && !failed
        ? <Image src={unit.previewUrl} alt={t('第 {value0} 页预览', { value0: unit.pageNumber })} fill unoptimized loading="lazy" sizes="(min-width: 1280px) 16vw, (min-width: 768px) 24vw, 45vw" className="object-contain" onError={() => setFailed(true)} />
        : <span className="m-auto flex flex-col items-center gap-2 px-3 text-center text-xs text-stone-500"><FileImage size={28} /><span>{t('预览暂不可用')}</span></span>}
      <span className="absolute bottom-2 right-2 rounded-full bg-stone-950/70 px-2 py-0.5 text-xs tabular-nums text-white">{unit.pageNumber}</span>
    </span>
    <span data-i18n-skip={unit.title ? '' : undefined} className="mt-2 block truncate text-sm font-medium text-stone-800">{title}</span>
  </button>;
}

export function ResourceDetailView({ resource, detail, loading, error, requestedPage, onBack, onPageChange }: Props) {
  const router = useRouter();
  const { t } = useI18n();
  const page = detail?.page.page ?? requestedPage;
  const totalPages = detail?.page.totalPages ?? 1;
  const readerHref = resource.readerType === 'audio' ? `/listen/${encodeURIComponent(resource.id)}` : `/reader/${encodeURIComponent(resource.id)}`;
  const chapters = detail?.units.filter((unit) => unit.unitType === 'chapter') ?? [];
  const pages = detail?.units.filter((unit): unit is ResourcePageDetailUnit => unit.unitType === 'page') ?? [];
  const tracks = detail?.units.filter((unit) => unit.unitType === 'track') ?? [];
  const chapterStates = resolveChapterReadingStates(
    chapters.map((unit) => ({ href: unit.href ?? undefined, sortOrder: unit.sortOrder })),
    detail?.currentHref,
    detail?.currentChapterSortOrder,
    detail?.progress ?? resource.progress,
    { page, pageSize: detail?.page.pageSize ?? 50, total: detail?.page.total ?? 0, currentIndex: detail?.currentChapterIndex }
  );
  const kind = resource.readerType === 'reflowable' ? 'chapter' : resource.readerType === 'audio' ? 'track' : 'page';
  const heading = kind === 'chapter' ? t('章节') : kind === 'track' ? t('音轨') : t('页面');
  const countLabel = kind === 'chapter' ? t('共 {value0} 章', { value0: detail?.page.total ?? 0 }) : kind === 'track' ? t('共 {value0} 条音轨', { value0: detail?.page.total ?? 0 }) : t('共 {value0} 页', { value0: detail?.page.total ?? 0 });

  return <section className="mt-6 border-t border-stone-200 pt-7" aria-busy={loading || undefined}>
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        {onBack ? <button type="button" onClick={onBack} className="inline-flex min-h-10 items-center gap-2 rounded-lg text-sm font-medium text-stone-600 hover:text-stone-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-200"><ArrowLeft size={17} />{t('返回图书内容')}</button> : null}
        <h2 className={cn('text-xl font-semibold text-stone-950', onBack && 'mt-3')}>{heading}</h2>
        <p className="mt-1 text-sm text-stone-500">{countLabel}</p>
      </div>
      <Button variant="secondary" icon={resource.readerType === 'audio' ? Headphones : undefined} onClick={() => router.push(readerHref)}>{t(resource.readerType === 'audio' ? '打开播放器' : '打开阅读器')}</Button>
    </div>

    {loading && !detail ? <div className="mt-6 flex min-h-40 items-center justify-center text-sm text-stone-500" role="status"><LoaderCircle size={19} className="mr-2 animate-spin text-[#ff4f2a] motion-reduce:animate-none" />{t('正在加载资源详情…')}</div> : null}
    {!loading && error ? <div className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-red-100 bg-red-50 px-4 py-4 text-sm text-red-700"><span className="inline-flex items-center gap-2"><AlertTriangle size={18} />{error}</span><Button variant="secondary" onClick={() => router.push(readerHref)}>{t(resource.readerType === 'audio' ? '打开播放器' : '打开阅读器')}</Button></div> : null}
    {!loading && !error && detail?.units.length === 0 ? <div className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-dashed border-stone-300 px-5 py-8 text-sm text-stone-600"><span>{t(kind === 'chapter' ? '暂无可定位章节' : kind === 'track' ? '暂无可播放音轨' : '当前资源没有可预览页面')}</span><Button variant="secondary" onClick={() => router.push(readerHref)}>{t(resource.readerType === 'audio' ? '打开播放器' : '打开阅读器')}</Button></div> : null}

    {chapters.length > 0 ? <div className={cn('mt-6 divide-y divide-stone-100 border-y border-stone-100', loading && 'opacity-60')}>
      {chapters.map((unit, index) => {
        const state = chapterStates[index] ?? 'unread';
        const href = resourceDetailItemHref(resource, unit);
        const displayIndex = (page - 1) * (detail?.page.pageSize ?? 50) + index + 1;
        return <button key={unit.id} type="button" disabled={!href} onClick={() => href && router.push(href)} className={cn('grid min-h-14 w-full grid-cols-[40px_minmax(0,1fr)_72px_24px] items-center gap-3 text-left text-sm transition hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50', state === 'current' && 'bg-[#fff4ef] hover:bg-[#fff4ef]')}>
          <span className="tabular-nums text-stone-400">{displayIndex}</span>
          <span data-i18n-skip={unit.title ? '' : undefined} className={cn('truncate font-medium', state === 'current' ? 'text-[#e84420]' : 'text-stone-800')} style={{ paddingInlineStart: `${Math.min(6, Math.max(0, unit.level ?? 0)) * 16}px` }}>{unit.title || t('第 {value0} 章', { value0: displayIndex })}</span>
          <span className={cn('text-xs', state === 'current' ? 'text-[#e84420]' : 'text-stone-400')}>{t(state === 'current' ? '正在阅读' : state === 'read' ? '已读' : '未读')}</span>
          {state === 'current' ? <BarChart3 size={18} className="text-[#ff4f26]" /> : state === 'read' ? <CheckCircle2 size={18} className="text-stone-400" /> : <Circle size={18} className="text-stone-400" />}
        </button>;
      })}
    </div> : null}

    {pages.length > 0 ? <div className={cn('mt-6 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6', loading && 'opacity-60')}>{pages.map((unit) => <PreviewTile key={unit.id} resource={resource} unit={unit} />)}</div> : null}

    {tracks.length > 0 ? <div className={cn('mt-6 divide-y divide-stone-100 overflow-hidden rounded-2xl border border-stone-200 bg-white', loading && 'opacity-60')}>
      {tracks.map((unit, index) => {
        const href = resourceDetailItemHref(resource, unit);
        const sequence = [unit.discNumber ? t('碟 {value0}', { value0: unit.discNumber }) : '', unit.trackNumber ? t('音轨 {value0}', { value0: unit.trackNumber }) : ''].filter(Boolean).join(' · ');
        return <button key={unit.id} type="button" disabled={!href} onClick={() => href && router.push(href)} className="grid min-h-16 w-full grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3 px-4 text-left transition hover:bg-[#fffaf7] disabled:cursor-not-allowed disabled:opacity-50">
          <span className="tabular-nums text-stone-400">{(page - 1) * (detail?.page.pageSize ?? 50) + index + 1}</span>
          <span className="min-w-0"><span data-i18n-skip className="block truncate text-sm font-medium text-stone-900">{unit.title}</span>{sequence ? <span className="mt-1 block text-xs text-stone-500">{sequence}</span> : null}</span>
          <span className="text-sm tabular-nums text-stone-500">{formatDuration(unit.durationMs)}</span>
        </button>;
      })}
    </div> : null}

    {detail && totalPages > 1 ? <nav className="mt-6 flex flex-wrap items-center justify-between gap-3" aria-label={t('资源详情分页')}><span className="text-sm tabular-nums text-stone-500">{t('第 {value0} / {value1} 页', { value0: page, value1: totalPages })}</span><div className="flex gap-2"><Button variant="secondary" disabled={loading || page <= 1} onClick={() => onPageChange(page - 1)}>{t('上一页')}</Button><Button variant="secondary" disabled={loading || page >= totalPages} onClick={() => onPageChange(page + 1)}>{t('下一页')}</Button></div></nav> : null}
  </section>;
}
