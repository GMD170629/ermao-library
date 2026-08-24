'use client';

import { BookOpen, Check, ChevronLeft, ChevronRight, Grid2X2, List, MoreVertical } from 'lucide-react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { Cover } from '../../../components/book/cover';
import { CoverReadingProgress, coverReadingProgressState } from '../../../components/book/cover-reading-progress';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import { Select } from '../../../components/ui/select';
import { I18nText, useI18n } from '../../../i18n/provider';
import type { BookView, ReadableResourceView } from '../../../types/book';
import type { BookContentEntry, BookContentLayout, BookContentSort, BookContentsPage } from '../model/book-contents';

type Props = Readonly<{
  book: BookView;
  contents: BookContentsPage | null;
  resources: readonly ReadableResourceView[];
  loading: boolean;
  error: string;
  layout: BookContentLayout;
  sort: BookContentSort;
  canManage: boolean;
  onLayoutChange: (layout: BookContentLayout) => void;
  onSortChange: (sort: BookContentSort) => void;
  onNavigate: (sourceNodeId: string | null, entry?: BookContentEntry) => void;
  onPageChange: (page: number) => void;
  onOpenResource: (resource: ReadableResourceView) => void;
  onManageResource: (resource: ReadableResourceView, anchor: HTMLButtonElement) => void;
  onManageSourceNode: (entry: BookContentEntry, anchor: HTMLButtonElement) => void;
}>;

function SourceNodeCard({ book, entry, resource, position, canManage, onOpen, onManage }: { book: BookView; entry: BookContentEntry; resource: ReadableResourceView | undefined; position: number; canManage: boolean; onOpen: () => void; onManage: (anchor: HTMLButtonElement) => void }) {
  const { t } = useI18n();
  return <article className="group relative min-w-0 rounded-2xl border border-stone-200 bg-white p-2 shadow-sm transition hover:border-orange-100 hover:shadow-md">
    <button type="button" onClick={onOpen} className="block w-full text-left focus-visible:outline-none" aria-label={t('打开来源目录 {value0}', { value0: entry.title })}>
      <div className="relative overflow-hidden rounded-xl bg-stone-100 shadow-sm transition group-hover:-translate-y-0.5 group-hover:shadow-md group-focus-within:outline group-focus-within:outline-2 group-focus-within:outline-offset-2 group-focus-within:outline-[#ff4f2a]">
        <Cover book={{ id: entry.sourceNodeId, title: entry.title, author: book.author, coverUrl: entry.coverUrl || resource?.coverUrl || book.coverUrl, gradient: book.gradient, coverStatus: entry.coverUrl || resource ? '' : book.coverStatus }} className="aspect-[2/3] w-full rounded-none" size="small" />
        <span className="absolute left-2 top-2 rounded-full bg-stone-950/55 px-2 py-0.5 text-[11px] font-medium tabular-nums text-white shadow-sm backdrop-blur-sm">{String(position + 1).padStart(2, '0')}</span>
      </div>
    </button>
    {canManage ? <button type="button" onClick={(event) => { event.stopPropagation(); onManage(event.currentTarget); }} onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); onManage(event.currentTarget); }} onKeyDown={(event) => { if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) { event.preventDefault(); event.stopPropagation(); onManage(event.currentTarget); } }} className="absolute right-4 top-4 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-stone-950/55 text-white shadow-sm backdrop-blur-sm transition hover:bg-stone-950/75" aria-label={t('管理 {value0}', { value0: entry.title })} aria-haspopup="menu"><MoreVertical size={17} /></button> : null}
    <button type="button" onClick={onOpen} className="mt-2 flex w-full items-start gap-2 rounded-lg px-1 pb-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-200">
      <span data-i18n-skip className="min-w-0 flex-1 line-clamp-2 text-sm font-semibold leading-5 text-stone-900">{entry.title}</span>
      <ChevronRight size={16} className="mt-0.5 shrink-0 text-stone-400" aria-hidden="true" />
    </button>
  </article>;
}

function ResourceCard({ book, resource, position, canManage, onOpen, onManage }: { book: BookView; resource: ReadableResourceView; position: number; canManage: boolean; onOpen: () => void; onManage: (anchor: HTMLButtonElement) => void }) {
  const { t } = useI18n();
  const progress = coverReadingProgressState(resource.progress);
  const number = position + 1;
  return <article className="group relative min-w-0" data-resource-card="true">
    <button type="button" onClick={onOpen} disabled={!resource.readable} aria-label={progress.visible ? t(resource.readerType === 'audio' ? '可读资源 {value0}，收听进度 {value1}%' : '可读资源 {value0}，阅读进度 {value1}%', { value0: number, value1: progress.roundedValue }) : t('可读资源 {value0}', { value0: number })} className={cn('block w-full text-left', !resource.readable && 'cursor-not-allowed opacity-50')}>
      <div className="relative overflow-hidden rounded-xl bg-stone-100 shadow-sm transition group-hover:-translate-y-0.5 group-hover:shadow-md group-focus-visible:outline group-focus-visible:outline-2 group-focus-visible:outline-offset-2 group-focus-visible:outline-[#ff4f2a]">
        <Cover book={{ id: resource.id, title: resource.title, author: book.author, coverUrl: resource.coverUrl, gradient: book.gradient, coverStatus: '' }} className="aspect-[2/3] w-full rounded-none" size="small" />
        <span className="absolute left-2 top-2 rounded-full bg-stone-950/55 px-2 py-0.5 text-[11px] font-medium tabular-nums text-white shadow-sm backdrop-blur-sm">{String(number).padStart(2, '0')}</span>
        {progress.roundedValue >= 100 ? <span className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-white shadow-sm"><Check size={14} strokeWidth={3} /></span> : null}
        <CoverReadingProgress progress={resource.progress} surface="resource" />
      </div>
    </button>
    {canManage ? <button type="button" onClick={(event: ReactMouseEvent<HTMLButtonElement>) => onManage(event.currentTarget)} onContextMenu={(event) => { event.preventDefault(); onManage(event.currentTarget); }} onKeyDown={(event) => { if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) { event.preventDefault(); onManage(event.currentTarget); } }} className="absolute right-2 top-2 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-stone-950/55 text-white shadow-sm backdrop-blur-sm transition hover:bg-stone-950/75" aria-label={t('管理 {value0}', { value0: resource.title })}><MoreVertical size={17} /></button> : null}
    <button type="button" onClick={onOpen} disabled={!resource.readable} className="mt-2 block w-full rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-200 disabled:cursor-not-allowed">
      <span data-i18n-skip className="block line-clamp-2 text-sm font-medium leading-5 text-stone-900">{resource.title}</span>
      <span className="mt-1 block truncate text-xs text-stone-500" data-i18n-skip>{[resource.format, resource.publisher, resource.language, resource.narrator].filter(Boolean).join(' · ')}</span>
    </button>
  </article>;
}

export function BookContentBrowser({ book, contents, resources, loading, error, layout, sort, canManage, onLayoutChange, onSortChange, onNavigate, onPageChange, onOpenResource, onManageResource, onManageSourceNode }: Props) {
  const { t } = useI18n();
  const resourcesById = new Map(resources.map((resource) => [resource.id, resource]));
  const currentResource = contents?.currentResourceId ? resourcesById.get(contents.currentResourceId) : undefined;
  const sourceNodes = (contents?.entries ?? []).filter((entry) => entry.kind === 'FOLDER');
  const childResources = (contents?.entries ?? []).flatMap((entry) => entry.kind === 'FILE' && entry.resourceId ? [resourcesById.get(entry.resourceId)].filter((resource): resource is ReadableResourceView => resource !== undefined) : []);
  const visibleResources = currentResource ? [currentResource, ...childResources.filter((resource) => resource.id !== currentResource.id)] : childResources;
  const itemCount = sourceNodes.length + visibleResources.length;
  const importSummary = book.resourceImportSummary;

  return <section className="mt-6 border-t border-stone-200 pt-8">
    <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <nav className="flex min-h-9 min-w-0 flex-wrap items-center gap-1 text-sm" aria-label={t('来源目录路径')}>
        <button type="button" onClick={() => onNavigate(null)} className="max-w-64 truncate rounded-lg px-2 py-1.5 font-medium text-stone-700 hover:bg-stone-100" data-i18n-skip>{book.title}</button>
        {(contents?.breadcrumbs ?? []).map((crumb) => <span key={crumb.sourceNodeId} className="contents"><ChevronRight size={14} className="text-stone-400" /><button type="button" onClick={() => onNavigate(crumb.sourceNodeId, crumb)} className="max-w-56 truncate rounded-lg px-2 py-1.5 text-stone-600 hover:bg-stone-100" data-i18n-skip>{crumb.title}</button></span>)}
      </nav>
      <div className="flex flex-wrap items-center gap-2" aria-label={t('图书内容显示控制')}>
        <div className="inline-flex rounded-xl border border-stone-200 bg-white p-1" role="group" aria-label={t('显示方式')}>
          <button type="button" aria-label={t('网格显示')} aria-pressed={layout === 'grid'} onClick={() => onLayoutChange('grid')} className={cn('flex h-9 w-9 items-center justify-center rounded-lg text-stone-500 transition', layout === 'grid' && 'bg-[#fff0ea] text-[#d94322]')}><Grid2X2 size={17} /></button>
          <button type="button" aria-label={t('列表显示')} aria-pressed={layout === 'list'} onClick={() => onLayoutChange('list')} className={cn('flex h-9 w-9 items-center justify-center rounded-lg text-stone-500 transition', layout === 'list' && 'bg-[#fff0ea] text-[#d94322]')}><List size={18} /></button>
        </div>
        <Select<BookContentSort> value={sort} ariaLabel="排序方式" size="sm" align="right" menuWidth={180} options={[{ value: 'name-asc', label: '名称 A–Z' }, { value: 'name-desc', label: '名称 Z–A' }, { value: 'updated-desc', label: '最近更新' }, { value: 'updated-asc', label: '最早更新' }, { value: 'type-asc', label: '内容类型' }, { value: 'size-desc', label: '内容大小' }]} onChange={onSortChange} />
      </div>
    </div>

    {error ? <p className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
    {importSummary.pending > 0 ? <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" role="status" aria-live="polite">
      {importSummary.ready > 0
        ? t('已有可读资源，另有 {value0} 个资源正在导入', { value0: importSummary.pending })
        : t('资源正在导入，请稍候')}
    </div> : null}
    {importSummary.ready === 0 && importSummary.pending === 0 && importSummary.failed > 0 ? <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert"><I18nText>资源导入失败</I18nText></div> : null}
    {loading ? <div className="flex min-h-48 items-center justify-center"><span className="text-sm text-stone-500"><I18nText>正在加载图书内容</I18nText></span></div> : null}
    {!loading && itemCount === 0 && importSummary.pending === 0 && importSummary.failed === 0 ? <div className="mt-5 rounded-2xl border border-dashed border-stone-300 p-10 text-center text-sm text-stone-500"><I18nText>没有可读资源</I18nText></div> : null}

    {!loading && itemCount > 0 && layout === 'grid' ? <div className="mt-6 grid grid-cols-2 gap-x-5 gap-y-7 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {sourceNodes.map((entry, index) => <SourceNodeCard key={entry.sourceNodeId} book={book} entry={entry} resource={entry.representativeResourceId ? resourcesById.get(entry.representativeResourceId) : undefined} position={index} canManage={canManage} onOpen={() => onNavigate(entry.sourceNodeId, entry)} onManage={(anchor) => onManageSourceNode(entry, anchor)} />)}
      {visibleResources.map((resource, index) => <ResourceCard key={resource.id} book={book} resource={resource} position={index} canManage={canManage} onOpen={() => onOpenResource(resource)} onManage={(anchor) => onManageResource(resource, anchor)} />)}
    </div> : null}

    {!loading && itemCount > 0 && layout === 'list' ? <div className="mt-6 overflow-hidden rounded-2xl border border-stone-200 bg-white">
      {sourceNodes.map((entry, index) => { const representative = entry.representativeResourceId ? resourcesById.get(entry.representativeResourceId) : undefined; return <div key={entry.sourceNodeId} className="flex items-center gap-3 border-b border-stone-100 px-4 py-3 hover:bg-[#fffaf7]"><button type="button" onClick={() => onNavigate(entry.sourceNodeId, entry)} className="flex min-w-0 flex-1 items-center gap-3 text-left"><Cover book={{ id: entry.sourceNodeId, title: entry.title, author: book.author, coverUrl: entry.coverUrl || representative?.coverUrl || book.coverUrl, gradient: book.gradient, coverStatus: entry.coverUrl || representative ? '' : book.coverStatus }} className="h-14 w-10 shrink-0 rounded-md" size="small" /><span className="min-w-0 flex-1"><span data-i18n-skip className="block truncate text-sm font-semibold text-stone-900">{entry.title}</span><span className="mt-1 block text-xs text-stone-500">{t('来源目录 {value0}', { value0: index + 1 })}</span></span><ChevronRight size={17} className="text-stone-400" /></button>{canManage ? <button type="button" onClick={(event) => onManageSourceNode(entry, event.currentTarget)} className="ml-2 flex h-9 w-9 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100" aria-label={t('管理 {value0}', { value0: entry.title })}><MoreVertical size={17} /></button> : null}</div>; })}
      {visibleResources.map((resource, index) => <div key={resource.id} className="flex items-center gap-3 border-b border-stone-100 px-4 py-3 last:border-b-0 hover:bg-[#fffaf7]"><button type="button" onClick={() => onOpenResource(resource)} className="flex min-w-0 flex-1 items-center gap-3 text-left"><Cover book={{ id: resource.id, title: resource.title, author: book.author, coverUrl: resource.coverUrl, gradient: book.gradient, coverStatus: '' }} className="h-14 w-10 shrink-0 rounded-md" size="small" /><span className="min-w-0 flex-1"><span data-i18n-skip className="block truncate text-sm font-medium text-stone-900">{resource.title}</span><span className="mt-1 block text-xs text-stone-500">{t('可读资源 {value0}', { value0: index + 1 })} · <span data-i18n-skip>{resource.format}</span></span></span><span className="text-sm tabular-nums text-stone-500">{Math.round(resource.progress)}%</span><BookOpen size={17} className="text-[#d94322]" /></button>{canManage ? <button type="button" onClick={(event) => onManageResource(resource, event.currentTarget)} className="ml-2 flex h-9 w-9 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100" aria-label={t('管理 {value0}', { value0: resource.title })}><MoreVertical size={17} /></button> : null}</div>)}
    </div> : null}

    {contents && contents.totalPages > 1 ? <div className="mt-5 flex items-center justify-end gap-2"><Button variant="secondary" icon={ChevronLeft} disabled={contents.page <= 1 || loading} onClick={() => onPageChange(contents.page - 1)}><I18nText>上一页</I18nText></Button><span className="px-2 text-sm tabular-nums text-stone-500">{t('第 {value0} / {value1} 页', { value0: contents.page, value1: contents.totalPages })}</span><Button variant="secondary" disabled={contents.page >= contents.totalPages || loading} onClick={() => onPageChange(contents.page + 1)}><I18nText>下一页</I18nText></Button></div> : null}
  </section>;
}
