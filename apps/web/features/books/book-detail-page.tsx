'use client';

import { ArrowLeft, BookOpen, Check, CheckCircle2, Download, Edit3, Ellipsis, EllipsisVertical, Headphones, Images, LoaderCircle, RefreshCw, Settings2, Sparkles, Trash2, X, type LucideIcon } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { Cover } from '../../components/book/cover';
import { CoverReadingProgress, coverReadingProgressState } from '../../components/book/cover-reading-progress';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { ContextActionMenu, type ContextMenuPosition } from '../../components/ui/context-action-menu';
import { useToast } from '../../components/ui/feedback';
import { Select } from '../../components/ui/select';
import { useAppSession } from '../../components/layout/app-session-context';
import type { MediaKind, ReaderType, ReadableResourceView, BookView } from '../../types/book';
import { I18nText, useI18n } from '@/i18n/provider';
import {
  deleteResourceSource,
  fetchBook,
  fetchEbookChapterDetail,
  regenerateBookCover,
  regenerateResourceCover,
  reclassifyResource,
  assetDownloadUrl,
  runResourceBatchAction,
  updateResource,
  updateResourceReadingStatus,
  uploadBookCover
} from './api/client';
import { useResourceWallSelection } from './application/use-resource-wall-selection';
import { BookMetadataEditor } from './ui/book-metadata-editor';
import { KindleSendModal } from './kindle-send-modal';
import { MetadataLookupModal } from './metadata-lookup-modal';
import { allVisibleResources, displayResourceNumber, formatDuration, mediaKindOfResource, selectedResourceForBook, bookDetailReturnHref } from './book-detail';
import { CHAPTER_DETAIL_PAGE_SIZE, singleResourceEbook, type EbookChapterDetail } from './model/chapter-detail';
import { currentPositionLabel } from './model/current-position-label';
import { resourceActionAvailability, type ResourceActionId } from './model/resource-action-menu';
import { SingleResourceChapterList } from './ui/single-resource-chapter-list';
import { bookActionIds, type BookActionId } from './model/book-action-menu';

type ResourceForm = Readonly<{
  publisher: string;
  publishedAt: string;
  language: string;
  isbn: string;
  identifier: string;
  narrator: string;
}>;

type ResourceCardActionId = 'edit' | 'regenerate-cover' | 'recognize' | 'delete';
type ResourceCardActionTarget = Readonly<{
  resourceId: string;
  title: string;
  assetCount: number;
}>;

const RESOURCE_CARD_ACTION_DETAILS: Record<ResourceCardActionId, { label: string; description: string; icon: LucideIcon; destructive?: boolean }> = {
  edit: { label: '编辑', description: '修改所选资源的出版元数据', icon: Edit3 },
  'regenerate-cover': { label: '重新生成封面', description: '从资源资产重新提取或生成封面', icon: RefreshCw },
  recognize: { label: '识别', description: '识别所选资源的出版元数据', icon: Sparkles },
  delete: { label: '删除', description: '永久删除对应的真实源资产', icon: Trash2, destructive: true }
};

const RESOURCE_ACTION_DETAILS: Record<ResourceActionId, { label: string; description: string; icon: LucideIcon }> = {
  download: { label: '下载', description: '下载所选资源的源资产', icon: Download },
  edit: { label: '编辑', description: '修改资源元数据', icon: Edit3 },
  'set-media-kind': { label: '设置媒体类型', description: '将资源归类为其他媒体类型', icon: Settings2 },
  'set-ebook': { label: '设置为电子书', description: '使用电子书方式管理和阅读', icon: BookOpen },
  'set-comic': { label: '设置为漫画', description: '使用漫画方式管理和阅读', icon: Images },
  'set-audiobook': { label: '设置为有声书', description: '使用有声书方式管理和收听', icon: Headphones }
};

function formForResource(resource: ReadableResourceView): ResourceForm {
  return {
    publisher: resource.publisher ?? '',
    publishedAt: resource.publishedAt?.slice(0, 10) ?? '',
    language: resource.language ?? '',
    isbn: resource.isbn ?? '',
    identifier: resource.identifier ?? '',
    narrator: resource.narrator ?? ''
  };
}

function readerHref(resource: ReadableResourceView): string {
  return resource.readerType === 'audio'
    ? `/listen/${encodeURIComponent(resource.id)}`
    : `/reader/${encodeURIComponent(resource.id)}`;
}

function consumptionCopy(readerType: ReaderType) {
  if (readerType === 'audio') return { progress: '收听进度', position: '当前收听', start: '开始听', resume: '继续听', status: '收听状态' } as const;
  if (readerType === 'comic') return { progress: '阅读进度', position: '当前资源', start: '开始看', resume: '继续看', status: '阅读状态' } as const;
  return { progress: '阅读进度', position: '当前位置', start: '开始阅读', resume: '继续阅读', status: '阅读状态' } as const;
}

function formatLabel(resource: ReadableResourceView): string {
  return [resource.format, resource.publisher, resource.language, resource.narrator].filter(Boolean).join(' · ');
}

function ResourceEditor({
  book,
  resource,
  onClose,
  onSaved
}: {
  book: BookView;
  resource: ReadableResourceView | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const feedback = useToast();
  const { t } = useI18n();
  const [form, setForm] = useState<ResourceForm | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => setForm(resource ? formForResource(resource) : null), [resource]);
  if (!resource || !form) return null;

  const save = async () => {
    setSaving(true);
    try {
      await updateResource(book.id, resource.id, {
        publisher: form.publisher.trim() || null,
        publishedAt: form.publishedAt.trim() || null,
        language: form.language.trim() || null,
        isbn: form.isbn.trim() || null,
        identifier: form.identifier.trim() || null,
        narrator: form.narrator.trim() || null
      });
      await onSaved();
      feedback.success(t('资源信息已保存'));
      onClose();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setSaving(false);
    }
  };

  return <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/45 md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('编辑资源')}>
    <div className="w-full max-w-xl rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>编辑资源</I18nText></h2><button type="button" onClick={onClose} aria-label={t('关闭')}><X size={20} /></button></div>
      <p data-i18n-skip className="mt-1 text-sm text-stone-500">{resource.title}</p>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="text-sm text-stone-600"><I18nText>出版社</I18nText><input value={form.publisher} onChange={(event) => setForm({ ...form, publisher: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>出版时间</I18nText><input type="date" value={form.publishedAt} onChange={(event) => setForm({ ...form, publishedAt: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>语言</I18nText><input value={form.language} onChange={(event) => setForm({ ...form, language: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>ISBN</I18nText><input value={form.isbn} onChange={(event) => setForm({ ...form, isbn: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>标识符</I18nText><input value={form.identifier} onChange={(event) => setForm({ ...form, identifier: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        {resource.readerType === 'audio' ? <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>朗读者</I18nText><input value={form.narrator} onChange={(event) => setForm({ ...form, narrator: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label> : null}
      </div>
      <div className="mt-6 flex justify-end gap-2"><Button variant="secondary" onClick={onClose}><I18nText>取消</I18nText></Button><Button loading={saving} onClick={() => void save()}><I18nText>保存</I18nText></Button></div>
    </div>
  </div>;
}

function ResourceCard({
  book,
  resource,
  position,
  canManage,
  managementMode,
  selected,
  onBeginSelection,
  onEnterSelection,
  onOpenContextMenu,
  onOpenActionMenu,
  onEdit,
  onRefresh
}: {
  book: BookView;
  resource: ReadableResourceView;
  position: number;
  canManage: boolean;
  managementMode: boolean;
  selected: boolean;
  onBeginSelection: (event: ReactMouseEvent<HTMLButtonElement>) => void;
  onEnterSelection: () => void;
  onOpenContextMenu: (position: ContextMenuPosition, anchor: HTMLButtonElement) => void;
  onOpenActionMenu: (position: ContextMenuPosition, anchor: HTMLButtonElement) => void;
  onEdit: () => void;
  onRefresh: () => Promise<void>;
}) {
  const router = useRouter();
  const feedback = useToast();
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [mediaKind, setMediaKind] = useState<MediaKind>(mediaKindOfResource(resource));
  const progress = coverReadingProgressState(resource.progress);

  const openActionMenu = (anchor: HTMLButtonElement) => {
    const bounds = anchor.getBoundingClientRect();
    onOpenActionMenu({ x: bounds.right, y: bounds.bottom + 6 }, anchor);
  };

  useEffect(() => setMediaKind(mediaKindOfResource(resource)), [resource]);

  const saveClassification = async (next: MediaKind) => {
    setBusy(true);
    try {
      await reclassifyResource(book.id, resource.id, next, 'RESOURCE');
      setMediaKind(next);
      await onRefresh();
      feedback.success(t('资源分类已更新'));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setBusy(false);
    }
  };

  return <article data-resource-card="true" className={cn('group relative min-w-0 text-left', selected && 'rounded-xl ring-2 ring-[#ff4f2a] ring-offset-2')}>
    <button
      type="button"
      onMouseDown={(event) => { if (canManage && managementMode) onBeginSelection(event); }}
      onMouseEnter={() => { if (canManage && managementMode) onEnterSelection(); }}
      onClick={() => { if (!managementMode && resource.readable) router.push(readerHref(resource)); }}
      onDoubleClick={() => { if (managementMode && resource.readable) router.push(readerHref(resource)); }}
      onContextMenu={(event) => {
        if (!canManage || !managementMode) return;
        event.preventDefault();
        event.stopPropagation();
        onOpenContextMenu({ x: event.clientX, y: event.clientY }, event.currentTarget);
      }}
      onKeyDown={(event) => {
        if (!canManage || !managementMode || (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10'))) return;
        event.preventDefault();
        event.stopPropagation();
        const bounds = event.currentTarget.getBoundingClientRect();
        onOpenContextMenu({ x: bounds.right, y: bounds.bottom + 6 }, event.currentTarget);
      }}
      aria-label={progress.visible ? t('第 {value0} 资源，进度 {value1}%', { value0: displayResourceNumber(resource, position), value1: progress.roundedValue }) : t('第 {value0} 资源', { value0: displayResourceNumber(resource, position) })}
      aria-pressed={canManage && managementMode ? selected : undefined}
      className={cn('block w-full text-left', !resource.readable && 'cursor-not-allowed opacity-50')}
    >
      <div className="relative overflow-hidden rounded-xl bg-stone-100 shadow-sm transition group-hover:-translate-y-0.5 group-hover:shadow-md">
        <Cover book={{ id: resource.id, title: resource.title, author: book.author, coverUrl: resource.coverUrl, gradient: book.gradient, coverStatus: '' }} className="aspect-[2/3] w-full rounded-none" size="small" />
        <span className="absolute left-2 top-2 rounded-full bg-stone-950/55 px-2 py-0.5 text-[11px] font-medium tabular-nums text-white shadow-sm backdrop-blur-sm">{String(displayResourceNumber(resource, position)).padStart(2, '0')}</span>
        {selected ? <span className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-full bg-[#ff4f2a] text-white shadow-sm"><Check size={14} strokeWidth={3} /></span> : null}
        <CoverReadingProgress progress={resource.progress} surface="resource" />
      </div>
    </button>
    {canManage ? <button
      type="button"
      onClick={(event) => { event.stopPropagation(); openActionMenu(event.currentTarget); }}
      onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); openActionMenu(event.currentTarget); }}
      onKeyDown={(event) => {
        if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return;
        event.preventDefault();
        event.stopPropagation();
        openActionMenu(event.currentTarget);
      }}
      className="absolute right-2 top-2 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-stone-950/55 text-white shadow-sm backdrop-blur-sm transition hover:bg-stone-950/75 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-stone-900"
      aria-label={t('管理 {value0}', { value0: resource.title })}
      aria-haspopup="menu"
    ><EllipsisVertical size={17} /></button> : null}
    <div className="mt-2 flex items-start gap-2">
      <span data-i18n-skip className="min-w-0 flex-1 line-clamp-2 text-sm font-medium leading-5 text-stone-900">{resource.title}</span>
      {canManage ? <button type="button" onClick={onEdit} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100" aria-label={t('编辑资源')}><Edit3 size={15} /></button> : null}
    </div>
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-stone-500">
      <span data-i18n-skip>{formatLabel(resource)}</span>
      {resource.durationMs ? <span data-i18n-skip>{formatDuration(resource.durationMs)}</span> : null}
    </div>
    {canManage && managementMode ? <div className="mt-2 flex gap-2">
      <Button variant="secondary" className="!min-h-8 !rounded-lg !px-2.5 !py-1 text-xs" disabled={busy} onClick={() => void saveClassification(mediaKind === 'EBOOK' ? 'COMIC' : 'EBOOK')}>{mediaKind === 'EBOOK' ? t('设为漫画') : t('设为电子书')}</Button>
      <Button variant="ghost" className="!min-h-8 !rounded-lg !px-2.5 !py-1 text-xs" disabled={busy} onClick={() => void saveClassification('AUDIOBOOK')}>{t('设为有声书')}</Button>
    </div> : null}
  </article>;
}

const ACTION_LABELS: Record<BookActionId, string> = {
  edit: '编辑信息',
  metadata: '元数据识别',
  'upload-cover': '上传自定义封面',
  'regenerate-cover': '重新生成封面',
  kindle: '发送到 Kindle'
};

export function BookDetailPage({ bookId }: { bookId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const feedback = useToast();
  const { t } = useI18n();
  const session = useAppSession();
  const canManage = session?.authorization?.canManageSystem === true;
  const [book, setBook] = useState<BookView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [managementMode, setManagementMode] = useState(false);
  const [metadataOpen, setMetadataOpen] = useState(false);
  const [metadataLookupOpen, setMetadataLookupOpen] = useState(false);
  const [metadataResourceId, setMetadataResourceId] = useState<string | null>(null);
  const [kindleOpen, setKindleOpen] = useState(false);
  const [coverRevision, setCoverRevision] = useState(0);
  const [resourceEditorId, setResourceEditorId] = useState<string | null>(null);
  const [resourceMenuPosition, setResourceMenuPosition] = useState<ContextMenuPosition | null>(null);
  const [resourceMenuAnchor, setResourceMenuAnchor] = useState<HTMLButtonElement | null>(null);
  const [resourceActionTarget, setResourceActionTarget] = useState<ResourceCardActionTarget | null>(null);
  const [resourceActionBusy, setResourceActionBusy] = useState<ResourceCardActionId | null>(null);
  const [readingStatusBusy, setReadingStatusBusy] = useState(false);
  const [chapterPage, setChapterPage] = useState(1);
  const [chapter, setChapter] = useState<EbookChapterDetail | null>(null);
  const [chapterLoading, setChapterLoading] = useState(false);
  const [chapterError, setChapterError] = useState('');
  const coverInputRef = useRef<HTMLInputElement>(null);
  const requestedResourceId = searchParams.get('resourceId')?.trim() || null;
  const returnHref = bookDetailReturnHref(searchParams.get('returnTo'));

  const refresh = useCallback(async () => {
    const next = await fetchBook(bookId, undefined, requestedResourceId);
    setBook(next);
  }, [bookId, requestedResourceId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void fetchBook(bookId, controller.signal, requestedResourceId)
      .then((next) => { setBook(next); setError(''); })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : t('读取图书失败')); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [bookId, requestedResourceId, t]);

  const resources = useMemo(() => book ? allVisibleResources(book) : [], [book]);
  const activeResource = book ? selectedResourceForBook(book, requestedResourceId) : null;
  const singleEbook = singleResourceEbook(resources);
  const selection = useResourceWallSelection({ enabled: canManage && managementMode, scopeKey: book?.id ?? '', resourceIds: resources.map((resource) => resource.id) });
  const selectedResources = resources.filter((resource) => selection.selectedIds.has(resource.id));
  const activeCopy = activeResource ? consumptionCopy(activeResource.readerType) : null;
  const activeReaderHref = activeResource?.readable ? readerHref(activeResource) : null;
  const activeProgress = activeResource?.progress ?? 0;
  const activeStatus = activeProgress >= 100 ? 'FINISHED' : activeProgress > 0 ? 'READING' : 'UNREAD';
  const actions = book ? bookActionIds({ canManage, kindleSendAvailable: resources.some((resource) => resource.kindleSendAvailable) }) : [];
  const batchResourceActions = resourceActionAvailability({
    canManage,
    readable: selectedResources.length > 0 && selectedResources.every((resource) => resource.readable),
    mediaKind: selectedResources.length === 1 ? mediaKindOfResource(selectedResources[0]!) : 'EBOOK',
    selectionCount: selectedResources.length
  });

  useEffect(() => {
    if (!book || !singleEbook) { setChapter(null); return; }
    const controller = new AbortController();
    setChapterLoading(true);
    setChapterError('');
    void fetchEbookChapterDetail(book.id, singleEbook.id, chapterPage, CHAPTER_DETAIL_PAGE_SIZE, controller.signal)
      .then(setChapter)
      .catch((reason) => { if (!controller.signal.aborted) setChapterError(reason instanceof Error ? reason.message : t('章节加载失败')); })
      .finally(() => { if (!controller.signal.aborted) setChapterLoading(false); });
    return () => controller.abort();
  }, [book, chapterPage, singleEbook, t]);

  const changeReadingStatus = async (status: string) => {
    if (!activeResource || (status !== 'UNREAD' && status !== 'FINISHED')) return;
    setReadingStatusBusy(true);
    try {
      await updateResourceReadingStatus(activeResource.id, status);
      await refresh();
      feedback.success(t(status === 'FINISHED' ? '已标记为已读' : '已标记为未读'));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('阅读状态更新失败'));
    } finally {
      setReadingStatusBusy(false);
    }
  };

  const downloadResource = (resource: ReadableResourceView | undefined) => {
    if (!resource?.readable) return;
    const assetId = resource.assets[0]?.id;
    if (!assetId) throw new Error(t('资源缺少可下载资产'));
    window.location.href = assetDownloadUrl(assetId);
  };

  const invokeAction = async (action: BookActionId) => {
    if (!book) return;
    if (action === 'edit') { setMetadataOpen(true); return; }
    if (action === 'metadata') { setMetadataLookupOpen(true); return; }
    if (action === 'upload-cover') { coverInputRef.current?.click(); return; }
    if (action === 'kindle') { setKindleOpen(true); return; }
    try {
      if (action === 'regenerate-cover') { await regenerateBookCover(book.id); setCoverRevision(Date.now()); feedback.success(t('封面已重新生成')); }
      await refresh();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    }
  };

  const invokeResourceAction = async (action: ResourceActionId) => {
    if (!book || selectedResources.length === 0) return;
    setResourceMenuPosition(null);
    if (action === 'edit') {
      const target = selectedResources[0];
      if (target) setResourceEditorId(target.id);
      return;
    }
    try {
      if (action === 'download') {
        if (selectedResources.length !== 1) return;
        downloadResource(selectedResources[0]);
      }
      if (action === 'set-ebook' || action === 'set-comic' || action === 'set-audiobook') {
        const targetMediaKind = action === 'set-ebook' ? 'EBOOK' : action === 'set-comic' ? 'COMIC' : 'AUDIOBOOK';
        await runResourceBatchAction(book.id, { action: 'SET_MEDIA_KIND', resourceIds: selectedResources.map((resource) => resource.id), targetMediaKind });
        await refresh();
        selection.clear();
      }
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    }
  };

  const invokeResourceCardAction = async (action: ResourceCardActionId) => {
    const target = resourceActionTarget;
    if (!book || !target) return;
    setResourceMenuPosition(null);
    setResourceActionTarget(null);
    if (action === 'edit') {
      setResourceEditorId(target.resourceId);
      return;
    }
    if (action === 'recognize') {
      setMetadataResourceId(target.resourceId);
      setMetadataLookupOpen(true);
      return;
    }
    if (action === 'delete') {
      const confirmed = await feedback.confirm({
        title: '永久删除源资产',
        description: t('将永久删除“{value0}”关联的 {value1} 个真实源资产，此操作无法恢复。', { value0: target.title, value1: target.assetCount }),
        confirmLabel: '永久删除',
        tone: 'danger',
        confirmationText: target.title
      });
      if (!confirmed) return;
    }
    setResourceActionBusy(action);
    try {
      if (action === 'regenerate-cover') {
        await regenerateResourceCover(book.id, target.resourceId);
        feedback.success(t('封面已重新生成'));
      } else if (action === 'delete') {
        await deleteResourceSource(book.id, target.resourceId, target.title);
        feedback.success(t('源资产已永久删除'));
      }
      await refresh();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setResourceActionBusy(null);
    }
  };

  if (loading && !book) return <div className="flex min-h-[60vh] items-center justify-center"><LoaderCircle className="animate-spin text-[#ff4f2a]" /></div>;
  if (!book) return <div className="mx-auto max-w-lg p-8 text-center"><p className="text-stone-600">{error || t('图书不存在')}</p><Button className="mt-4" onClick={() => router.push(returnHref)}><I18nText>返回书库</I18nText></Button></div>;

  return <div className="w-full">
    <button type="button" onClick={() => router.push(returnHref)} className="mb-6 inline-flex items-center gap-2 text-sm text-stone-600 hover:text-stone-950"><ArrowLeft size={17} /><I18nText>返回全部图书</I18nText></button>
    <section className="rounded-[22px] border border-[#f1ddd3] bg-[#fffaf7] p-5 sm:p-6">
      <div className="grid gap-6 lg:grid-cols-[190px_minmax(0,1fr)_230px]">
        <Cover book={{ id: book.id, title: book.title, author: book.author, coverUrl: coverRevision > 0 && book.coverUrl ? `${book.coverUrl}${book.coverUrl.includes('?') ? '&' : '?'}v=${coverRevision}` : book.coverUrl, gradient: book.gradient, coverStatus: book.coverStatus }} className="mx-auto aspect-[2/3] w-36 rounded-xl shadow-md sm:w-[190px] lg:mx-0" size="large" priority />
        <div className="flex min-w-0 flex-col py-1">
          {book.completed ? <span className="inline-flex w-fit items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"><CheckCircle2 size={14} /><I18nText>已完成</I18nText></span> : null}
          <h1 data-i18n-skip className="mt-2 line-clamp-2 text-3xl font-semibold leading-[1.15] tracking-tight text-stone-950 sm:text-[34px]">{book.title}</h1>
          <p data-i18n-skip className="mt-3 text-base text-stone-600">{book.author}</p>
          {book.description ? <p data-i18n-skip className="mt-5 line-clamp-3 max-w-3xl whitespace-pre-line text-sm leading-7 text-stone-600">{book.description}</p> : <p className="mt-5 text-sm text-stone-400"><I18nText>暂无简介</I18nText></p>}
          {activeCopy ? <div className="mt-7 max-w-3xl">
            <div className="flex items-center gap-4"><span className="shrink-0 text-sm font-medium text-stone-700">{t(activeCopy.progress)}</span><div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-stone-200"><div className="h-full rounded-full bg-[#ff4f26]" style={{ width: `${activeProgress}%` }} /></div><span className="w-14 text-right text-sm font-medium tabular-nums text-stone-700">{Math.round(activeProgress)}%</span></div>
            <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm"><span className="font-medium text-stone-700">{t(activeCopy.position)}</span><span data-i18n-skip className="text-stone-800">{activeResource ? currentPositionLabel(activeResource, chapter, t) : ''}</span></div>
          </div> : null}
          {error ? <p className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
        </div>
        <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end lg:col-start-2 xl:col-start-3 xl:flex-col xl:justify-end">
          {activeCopy ? <Button disabled={!activeReaderHref} icon={activeResource?.readerType === 'audio' ? Headphones : activeResource?.readerType === 'comic' ? Images : BookOpen} onClick={() => activeReaderHref && router.push(activeReaderHref)} className="!h-12 !min-h-12 w-full !rounded-xl !bg-[#ff4f26] !px-8 !text-base !text-white hover:!bg-[#e84420]">{t(activeProgress > 0 ? activeCopy.resume : activeCopy.start)}</Button> : null}
          <div className="flex w-full gap-2">
            {activeCopy && activeResource ? <Select value={activeStatus} options={[{ value: 'READING', label: '在读', disabled: activeStatus !== 'READING' }, { value: 'UNREAD', label: '未读' }, { value: 'FINISHED', label: '已读' }]} onChange={(status) => void changeReadingStatus(status)} ariaLabel={t(activeCopy.status)} disabled={readingStatusBusy} className="min-w-0 flex-1" /> : null}
            {actions.length ? <div className="relative ml-auto"><details className="group"><summary className="flex h-11 w-12 cursor-pointer list-none items-center justify-center rounded-xl border border-[#ead8cf] bg-white/80 text-stone-600" aria-label={t('更多图书操作')}><Ellipsis size={20} /></summary><div className="absolute right-0 top-full z-40 mt-2 w-60 rounded-[18px] border border-stone-200 bg-white p-2 shadow-xl">{actions.map((action) => <button key={action} type="button" onClick={() => void invokeAction(action)} className="flex min-h-10 w-full items-center gap-3 rounded-xl px-3 text-left text-sm text-stone-700 hover:bg-stone-50"><span>{t(ACTION_LABELS[action])}</span></button>)}</div></details></div> : null}
          </div>
        </div>
      </div>
    </section>

    <input ref={coverInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; void uploadBookCover(book.id, file).then(() => { setCoverRevision(Date.now()); return refresh(); }).catch((reason) => feedback.error(reason instanceof Error ? reason.message : t('操作失败'))); event.currentTarget.value = ''; }} />
    <BookMetadataEditor book={book} open={metadataOpen} onClose={() => setMetadataOpen(false)} onSaved={(nextBook) => { setBook(nextBook); setMetadataOpen(false); }} />

    <section className="mt-6 border-t border-stone-200 pt-8">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-lg font-semibold text-stone-950"><I18nText>可读资源</I18nText></h2><p className="mt-1 text-sm text-stone-500">{t('{value0} 个资源', { value0: resources.length })}</p></div>{canManage ? <Button variant={managementMode ? 'secondary' : 'primary'} icon={Settings2} onClick={() => setManagementMode((value) => !value)} className={cn('!rounded-xl', !managementMode && '!bg-[#ff4f26] !text-white hover:!bg-[#e84420]')}>{managementMode ? t('完成管理') : t('管理资源')}</Button> : null}</div>
      {managementMode && selectedResources.length > 0 ? <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl bg-stone-50 p-3"><span className="text-sm text-stone-600">{t('已选 {value0} 个资源', { value0: selectedResources.length })}</span>{resourceActionAvailability({ canManage, readable: selectedResources.every((resource) => resource.readable), mediaKind: selectedResources.length === 1 ? mediaKindOfResource(selectedResources[0]!) : 'EBOOK', selectionCount: selectedResources.length }).map(({ action, disabled }) => <Button key={action} variant="secondary" className="!min-h-9 !rounded-lg !px-3 !py-1.5 text-xs" disabled={disabled} onClick={() => void invokeResourceAction(action)}>{action === 'download' ? t('下载') : action === 'edit' ? t('编辑') : action === 'set-media-kind' ? t('设置类型') : action === 'set-ebook' ? t('电子书') : action === 'set-comic' ? t('漫画') : t('有声书')}</Button>)}</div> : null}
      {loading ? <div className="flex min-h-48 items-center justify-center"><LoaderCircle className="animate-spin text-[#ff4f2a]" /></div> : resources.length ? <div data-resource-wall-selection-surface="true" onClick={(event) => { if (event.target === event.currentTarget) selection.clear(); }} className="mt-6 grid grid-cols-[repeat(auto-fill,minmax(130px,160px))] gap-5">{resources.map((resource, index) => <ResourceCard
        key={resource.id}
        book={book}
        resource={resource}
        position={index}
        canManage={canManage}
        managementMode={managementMode}
        selected={selection.selectedIds.has(resource.id)}
        onBeginSelection={(event) => {
          setResourceMenuPosition(null);
          selection.beginCardSelection(event, resource.id);
        }}
        onEnterSelection={() => selection.enterCard(resource.id)}
        onOpenContextMenu={(position, anchor) => {
          selection.selectForContextMenu(resource.id);
          setResourceMenuAnchor(anchor);
          setResourceMenuPosition(position);
        }}
        onOpenActionMenu={(position, anchor) => {
          setResourceActionTarget({ resourceId: resource.id, title: resource.title, assetCount: resource.assets.length });
          setResourceMenuAnchor(anchor);
          setResourceMenuPosition(position);
        }}
        onEdit={() => setResourceEditorId(resource.id)}
        onRefresh={refresh}
      />)}</div> : <div className="mt-6 rounded-2xl border border-dashed border-stone-300 p-10 text-center text-sm text-stone-500"><I18nText>该图书还没有可读资源</I18nText></div>}
      {singleEbook && !managementMode ? <SingleResourceChapterList resource={singleEbook} detail={chapter} loading={chapterLoading} error={chapterError} requestedPage={chapterPage} onPageChange={setChapterPage} /> : null}
    </section>

    {canManage && selectedResources.length > 0 && !resourceActionTarget ? <ContextActionMenu<ResourceActionId>
      position={resourceMenuPosition}
      ariaLabel={t('管理资源')}
      title={selectedResources.length === 1 ? selectedResources[0]?.title ?? '' : t('批量管理资源')}
      badge={t('已选 {value0} 个资源', { value0: selectedResources.length })}
      items={batchResourceActions.filter(({ action }) => action !== 'set-ebook' && action !== 'set-comic' && action !== 'set-audiobook').map(({ action, disabled }) => {
        const details = RESOURCE_ACTION_DETAILS[action];
        return {
          action,
          label: t(details.label),
          description: t(details.description),
          icon: details.icon,
          disabled,
          submenu: action === 'set-media-kind' ? batchResourceActions.filter((candidate) => candidate.action === 'set-ebook' || candidate.action === 'set-comic' || candidate.action === 'set-audiobook').map((candidate) => {
            const submenuDetails = RESOURCE_ACTION_DETAILS[candidate.action];
            return { action: candidate.action, label: t(submenuDetails.label), description: t(submenuDetails.description), icon: submenuDetails.icon, disabled: candidate.disabled };
          }) : undefined
        };
      })}
      footer={t('Ctrl/Command + 点击可多选；按住左键扫过可快速选择；双击打开。')}
      returnFocusTo={resourceMenuAnchor}
      onClose={() => setResourceMenuPosition(null)}
      onSelect={(action) => { void invokeResourceAction(action); }}
    /> : null}

    {canManage && resourceActionTarget ? <ContextActionMenu<ResourceCardActionId>
      position={resourceMenuPosition}
      ariaLabel={t('管理资源')}
      title={resourceActionTarget.title}
      items={(Object.entries(RESOURCE_CARD_ACTION_DETAILS) as Array<[ResourceCardActionId, (typeof RESOURCE_CARD_ACTION_DETAILS)[ResourceCardActionId]]>).map(([action, details]) => ({
        action,
        label: t(details.label),
        description: t(details.description),
        icon: details.icon,
        destructive: details.destructive,
        disabled: resourceActionBusy !== null,
        separatorBefore: action === 'delete'
      }))}
      returnFocusTo={resourceMenuAnchor}
      onClose={() => { setResourceMenuPosition(null); setResourceActionTarget(null); }}
      onSelect={(action) => { void invokeResourceCardAction(action); }}
    /> : null}

    <ResourceEditor book={book} resource={resources.find((resource) => resource.id === resourceEditorId) ?? null} onClose={() => setResourceEditorId(null)} onSaved={refresh} />
    <MetadataLookupModal book={book} currentResourceId={metadataResourceId ?? activeResource?.id ?? null} fixedScope={metadataResourceId ? 'resource' : null} open={metadataLookupOpen} onClose={() => { setMetadataLookupOpen(false); setMetadataResourceId(null); }} onApplied={refresh} />
    <KindleSendModal book={book} open={kindleOpen} preferredResourceId={activeResource?.id ?? null} onClose={() => setKindleOpen(false)} />
  </div>;
}
