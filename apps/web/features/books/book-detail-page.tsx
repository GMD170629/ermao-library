'use client';

import { ArrowLeft, BookOpen, CheckCircle2, Edit3, Ellipsis, Headphones, Images, LoaderCircle, RefreshCw, ScanSearch, Sparkles, Trash2, X, type LucideIcon } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Cover } from '../../components/book/cover';
import { Button } from '../../components/ui/button';
import { ContextActionMenu, type ContextMenuPosition } from '../../components/ui/context-action-menu';
import { useToast } from '../../components/ui/feedback';
import { Select } from '../../components/ui/select';
import { useAppSession } from '../../components/layout/app-session-context';
import type { ReaderType, ReadableResourceView, BookView } from '../../types/book';
import { I18nText, useI18n } from '@/i18n/provider';
import {
  deleteResourceSource,
  continueSourceNode,
  fetchBook,
  fetchBookContents,
  fetchResourceDetail,
  regenerateBookCover,
  regenerateResourceCover,
  updateResource,
  updateResourceReadingStatus,
  uploadBookCover
} from './api/client';
import { BookMetadataEditor } from './ui/book-metadata-editor';
import { KindleSendModal } from './kindle-send-modal';
import { MetadataLookupModal } from './metadata-lookup-modal';
import { allVisibleResources, selectedResourceForBook, bookDetailHref, bookDetailReturnHref, resourcePageFromQuery, singleReadableResourceForBook } from './book-detail';
import { resourceDetailPageSize, type ResourceDetailPage } from './model/resource-detail';
import type { BookContentLayout, BookContentSort, BookContentsPage } from './model/book-contents';
import type { BookContentEntry } from './model/book-contents';
import { currentPositionLabel } from './model/current-position-label';
import { BookContentBrowser } from './ui/book-content-browser';
import { ResourceDetailView } from './ui/resource-detail-view';
import { SourceNodeMetadataEditor, SourceNodeMetadataRecognitionDialog } from './ui/source-node-metadata-dialogs';
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

type SourceNodeActionId = 'edit' | 'regenerate-cover' | 'recognize' | 'rescan';

const SOURCE_NODE_ACTION_DETAILS: Record<SourceNodeActionId, { label: string; description: string; icon: LucideIcon }> = {
  edit: { label: '编辑', description: '修改所选来源目录的标题、简介和封面', icon: Edit3 },
  'regenerate-cover': { label: '重新生成封面', description: '从来源目录中的可读资源重新提取或生成封面', icon: RefreshCw },
  recognize: { label: '识别元数据', description: '从元数据来源搜索并应用来源目录信息', icon: Sparkles },
  rescan: { label: '重新扫描文件', description: '重新扫描该来源目录下的文件变化', icon: ScanSearch }
};

const RESOURCE_CARD_ACTION_DETAILS: Record<ResourceCardActionId, { label: string; description: string; icon: LucideIcon; destructive?: boolean }> = {
  edit: { label: '编辑', description: '修改所选可读资源的出版元数据', icon: Edit3 },
  'regenerate-cover': { label: '重新生成封面', description: '从可读资源内容重新提取或生成封面', icon: RefreshCw },
  recognize: { label: '识别', description: '识别所选可读资源的出版元数据', icon: Sparkles },
  delete: { label: '删除', description: '永久删除对应的真实源资产', icon: Trash2, destructive: true }
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
  if (readerType === 'comic') return { progress: '阅读进度', position: '当前位置', start: '开始看', resume: '继续看', status: '阅读状态' } as const;
  return { progress: '阅读进度', position: '当前位置', start: '开始阅读', resume: '继续阅读', status: '阅读状态' } as const;
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
      feedback.success(t('可读资源信息已保存'));
      onClose();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setSaving(false);
    }
  };

  return <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/45 md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('编辑可读资源')}>
    <div className="w-full max-w-xl rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>编辑可读资源</I18nText></h2><button type="button" onClick={onClose} aria-label={t('关闭')}><X size={20} /></button></div>
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
  const [contentLayout, setContentLayout] = useState<BookContentLayout>('grid');
  const [contentSort, setContentSort] = useState<BookContentSort>('name-asc');
  const [contentSourceNodeId, setContentSourceNodeId] = useState<string | null>(null);
  const [contentPage, setContentPage] = useState(1);
  const [contents, setContents] = useState<BookContentsPage | null>(null);
  const [selectedContentNode, setSelectedContentNode] = useState<BookContentEntry | null>(null);
  const [contentsLoading, setContentsLoading] = useState(true);
  const [contentsError, setContentsError] = useState('');
  const [contentsRevision, setContentsRevision] = useState(0);
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
  const [sourceNodeActionTarget, setSourceNodeActionTarget] = useState<BookContentEntry | null>(null);
  const [sourceNodeMenuPosition, setSourceNodeMenuPosition] = useState<ContextMenuPosition | null>(null);
  const [sourceNodeMenuAnchor, setSourceNodeMenuAnchor] = useState<HTMLButtonElement | null>(null);
  const [sourceNodeActionBusy, setSourceNodeActionBusy] = useState<SourceNodeActionId | null>(null);
  const [sourceNodeEditorTarget, setSourceNodeEditorTarget] = useState<BookContentEntry | null>(null);
  const [sourceNodeRecognitionTarget, setSourceNodeRecognitionTarget] = useState<BookContentEntry | null>(null);
  const [readingStatusBusy, setReadingStatusBusy] = useState(false);
  const [resourceDetail, setResourceDetail] = useState<ResourceDetailPage | null>(null);
  const [resourceDetailLoading, setResourceDetailLoading] = useState(false);
  const [resourceDetailError, setResourceDetailError] = useState('');
  const coverInputRef = useRef<HTMLInputElement>(null);
  const requestedResourceId = searchParams.get('resourceId')?.trim() || null;
  const requestedResourcePage = resourcePageFromQuery(searchParams.get('resourcePage'));
  const returnHref = bookDetailReturnHref(searchParams.get('returnTo'));

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const next = await fetchBook(bookId, signal, requestedResourceId);
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

  useEffect(() => {
    if (!book || book.resourceImportSummary.pending === 0) return;
    let controller: AbortController | null = null;
    const refreshPendingResources = () => {
      if (document.visibilityState !== 'visible') return;
      controller?.abort();
      controller = new AbortController();
      void refresh(controller.signal)
        .then(() => setContentsRevision((current) => current + 1))
        .catch(() => undefined);
    };
    const intervalId = window.setInterval(refreshPendingResources, 2_000);
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') refreshPendingResources();
    };
    document.addEventListener('visibilitychange', refreshWhenVisible);
    window.addEventListener('focus', refreshPendingResources);
    return () => {
      controller?.abort();
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
      window.removeEventListener('focus', refreshPendingResources);
    };
  }, [book, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    setContentsLoading(true);
    setContentsError('');
    void fetchBookContents(bookId, contentSourceNodeId, contentSort, contentPage, controller.signal)
      .then((next) => {
        setContents(next);
        if (contentSourceNodeId && next.currentNode) setSelectedContentNode(next.currentNode);
      })
      .catch((reason) => { if (!controller.signal.aborted) setContentsError(reason instanceof Error ? reason.message : t('读取图书内容失败')); })
      .finally(() => { if (!controller.signal.aborted) setContentsLoading(false); });
    return () => controller.abort();
  }, [bookId, contentPage, contentSort, contentSourceNodeId, contentsRevision, t]);

  const resources = useMemo(() => book ? allVisibleResources(book) : [], [book]);
  const singleReadableResource = book ? singleReadableResourceForBook(book) : null;
  const bookAnchoredResource = book
    ? resources.find((resource) => resource.sourceNodeId === book.sourceNodeId) ?? null
    : null;
  const selectedBookResource = book ? selectedResourceForBook(book, requestedResourceId) : null;
  const requestedResource = requestedResourceId
    ? resources.find((resource) => resource.id === requestedResourceId && resource.readable) ?? null
    : singleReadableResource;
  const nestedNode = contentSourceNodeId
    ? contents?.currentNode?.sourceNodeId === contentSourceNodeId
      ? contents.currentNode
      : selectedContentNode?.sourceNodeId === contentSourceNodeId
        ? selectedContentNode
        : null
    : null;
  const nestedResources = nestedNode ? (contents?.currentResourceIds ?? []).flatMap((id) => {
    const resource = resources.find((candidate) => candidate.id === id);
    return resource ? [resource] : [];
  }) : [];
  const activeResource = nestedNode
    ? nestedResources.find((resource) => resource.progress > 0 && resource.progress < 100)
      ?? nestedResources.find((resource) => resource.progress < 100)
      ?? nestedResources[0]
      ?? null
    : selectedBookResource;
  const displayedTitle = nestedNode?.title ?? book?.title ?? '';
  const displayedDescription = nestedNode?.description ?? (nestedNode ? '' : book?.description ?? '');
  const displayedCoverUrl = activeResource?.coverUrl || book?.coverUrl || '';
  const displayedProgress = nestedNode && nestedResources.length > 0
    ? nestedResources.reduce((total, resource) => total + resource.progress, 0) / nestedResources.length
    : activeResource?.progress ?? 0;
  const displayedCompleted = nestedNode
    ? nestedResources.length > 0 && nestedResources.every((resource) => resource.progress >= 100)
    : book?.completed === true;
  const activeCopy = activeResource ? consumptionCopy(activeResource.readerType) : null;
  const activeReaderHref = activeResource?.readable ? readerHref(activeResource) : null;
  const activeProgress = displayedProgress;
  const activeStatus = activeProgress >= 100 ? 'FINISHED' : activeProgress > 0 ? 'READING' : 'UNREAD';
  const actions = book ? bookActionIds({ canManage, canRegenerateCover: bookAnchoredResource !== null, kindleSendAvailable: resources.some((resource) => resource.kindleSendAvailable) }) : [];

  useEffect(() => {
    if (!book || requestedResourceId || !singleReadableResource) return;
    router.replace(bookDetailHref(book.id, singleReadableResource.id, searchParams.get('returnTo'), 1));
  }, [book, requestedResourceId, router, searchParams, singleReadableResource]);

  useEffect(() => {
    if (!book || !requestedResource) {
      setResourceDetail(null);
      setResourceDetailError('');
      setResourceDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    setResourceDetailLoading(true);
    setResourceDetailError('');
    void fetchResourceDetail(book.id, requestedResource.id, requestedResourcePage, resourceDetailPageSize(requestedResource), controller.signal)
      .then((next) => { setResourceDetail(next); setResourceDetailError(''); })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        setResourceDetail(null);
        setResourceDetailError(reason instanceof Error ? reason.message : t('资源详情加载失败'));
      })
      .finally(() => { if (!controller.signal.aborted) setResourceDetailLoading(false); });
    return () => controller.abort();
  }, [book, requestedResource, requestedResourcePage, t]);

  const updateResourceLocation = (resourceId: string | null, page?: number) => {
    router.push(bookDetailHref(bookId, resourceId, searchParams.get('returnTo'), resourceId ? page ?? 1 : null));
  };

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

  const invokeAction = async (action: BookActionId) => {
    if (!book) return;
    if (action === 'edit') { setMetadataOpen(true); return; }
    if (action === 'metadata') { setMetadataLookupOpen(true); return; }
    if (action === 'upload-cover') { coverInputRef.current?.click(); return; }
    if (action === 'kindle') { setKindleOpen(true); return; }
    try {
      if (action === 'regenerate-cover') {
        if (!bookAnchoredResource) throw new Error(t('图书来源节点没有可重新提取封面的资源'));
        await regenerateBookCover(book.id, bookAnchoredResource.id);
        setCoverRevision(Date.now());
        feedback.success(t('封面已重新生成'));
      }
      await refresh();
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
      setContentsRevision((value) => value + 1);
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setResourceActionBusy(null);
    }
  };

  const invokeSourceNodeAction = async (action: SourceNodeActionId) => {
    const target = sourceNodeActionTarget;
    if (!book || !target) return;
    setSourceNodeMenuPosition(null);
    setSourceNodeActionTarget(null);
    if (action === 'edit') {
      setSourceNodeEditorTarget(target);
      return;
    }
    if (action === 'recognize') {
      setSourceNodeRecognitionTarget(target);
      return;
    }
    setSourceNodeActionBusy(action);
    try {
      if (action === 'regenerate-cover') {
        if (!target.representativeResourceId) throw new Error(t('该来源目录还没有可用于生成封面的可读资源'));
        await regenerateResourceCover(book.id, target.representativeResourceId);
        setCoverRevision(Date.now());
        feedback.success(t('封面已重新生成'));
      } else {
        await continueSourceNode(target.sourceNodeId);
        feedback.success(t('已加入重新扫描队列'));
      }
      await refresh();
      setContentsRevision((value) => value + 1);
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setSourceNodeActionBusy(null);
    }
  };

  if (loading && !book) return <div className="flex min-h-[60vh] items-center justify-center"><LoaderCircle className="animate-spin text-[#ff4f2a]" /></div>;
  if (!book) return <div className="mx-auto max-w-lg p-8 text-center"><p className="text-stone-600">{error || t('图书不存在')}</p><Button className="mt-4" onClick={() => router.push(returnHref)}><I18nText>返回书库</I18nText></Button></div>;

  return <div className="w-full">
    <button type="button" onClick={() => router.push(returnHref)} className="mb-6 inline-flex items-center gap-2 text-sm text-stone-600 hover:text-stone-950"><ArrowLeft size={17} /><I18nText>返回全部图书</I18nText></button>
    <section className="rounded-[22px] border border-[#f1ddd3] bg-[#fffaf7] p-5 sm:p-6">
      <div className="grid gap-6 lg:grid-cols-[190px_minmax(0,1fr)_230px]">
        <Cover book={{ id: nestedNode?.sourceNodeId ?? book.id, title: displayedTitle, author: book.author, coverUrl: coverRevision > 0 && displayedCoverUrl ? `${displayedCoverUrl}${displayedCoverUrl.includes('?') ? '&' : '?'}v=${coverRevision}` : displayedCoverUrl, gradient: book.gradient, coverStatus: activeResource ? '' : book.coverStatus }} className="mx-auto aspect-[2/3] w-36 rounded-xl shadow-md sm:w-[190px] lg:mx-0" size="large" priority />
        <div className="flex min-w-0 flex-col py-1">
          {displayedCompleted ? <span className="inline-flex w-fit items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"><CheckCircle2 size={14} /><I18nText>已完成</I18nText></span> : null}
          <h1 data-i18n-skip className="mt-2 line-clamp-2 text-3xl font-semibold leading-[1.15] tracking-tight text-stone-950 sm:text-[34px]">{displayedTitle}</h1>
          <p data-i18n-skip className="mt-3 text-base text-stone-600">{book.author}</p>
          {displayedDescription ? <p data-i18n-skip className="mt-5 line-clamp-3 max-w-3xl whitespace-pre-line text-sm leading-7 text-stone-600">{displayedDescription}</p> : <p className="mt-5 text-sm text-stone-400"><I18nText>暂无简介</I18nText></p>}
          {activeCopy ? <div className="mt-7 max-w-3xl">
            <div className="flex items-center gap-4"><span className="shrink-0 text-sm font-medium text-stone-700">{t(activeCopy.progress)}</span><div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-stone-200"><div className="h-full rounded-full bg-[#ff4f26]" style={{ width: `${activeProgress}%` }} /></div><span className="w-14 text-right text-sm font-medium tabular-nums text-stone-700">{Math.round(activeProgress)}%</span></div>
            <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm"><span className="font-medium text-stone-700">{t(activeCopy.position)}</span><span data-i18n-skip className="text-stone-800">{activeResource ? currentPositionLabel(activeResource, requestedResource?.id === activeResource.id ? resourceDetail : null, t) : ''}</span></div>
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

    <input ref={coverInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; void uploadBookCover(book, file).then(() => { setCoverRevision(Date.now()); return refresh(); }).catch((reason) => feedback.error(reason instanceof Error ? reason.message : t('操作失败'))); event.currentTarget.value = ''; }} />
    <BookMetadataEditor book={book} open={metadataOpen} onClose={() => setMetadataOpen(false)} onSaved={(nextBook) => { setBook(nextBook); setMetadataOpen(false); }} />

    {requestedResource ? <ResourceDetailView
      resource={requestedResource}
      detail={resourceDetail}
      loading={resourceDetailLoading}
      error={resourceDetailError}
      requestedPage={requestedResourcePage}
      onBack={singleReadableResource ? null : () => updateResourceLocation(null)}
      onPageChange={(page) => updateResourceLocation(requestedResource.id, page)}
    /> : <BookContentBrowser
      book={book}
      contents={contents}
      resources={resources}
      loading={contentsLoading}
      error={contentsError}
      layout={contentLayout}
      sort={contentSort}
      canManage={canManage}
      onLayoutChange={setContentLayout}
      onSortChange={(value) => { setContentSort(value); setContentPage(1); }}
      onNavigate={(sourceNodeId, entry) => {
        setContentSourceNodeId(sourceNodeId);
        setSelectedContentNode(entry ?? null);
        setContentPage(1);
      }}
      onPageChange={setContentPage}
      onOpenResource={(resource) => updateResourceLocation(resource.id, 1)}
      onManageResource={(resource, anchor) => {
        const bounds = anchor.getBoundingClientRect();
        setResourceActionTarget({ resourceId: resource.id, title: resource.title, assetCount: resource.assets.length });
        setResourceMenuAnchor(anchor);
        setResourceMenuPosition({ x: bounds.right, y: bounds.bottom + 6 });
      }}
      onManageSourceNode={(entry, anchor) => {
        const bounds = anchor.getBoundingClientRect();
        setSourceNodeActionTarget(entry);
        setSourceNodeMenuAnchor(anchor);
        setSourceNodeMenuPosition({ x: bounds.right, y: bounds.bottom + 6 });
      }}
    />}

    {canManage && sourceNodeActionTarget ? <ContextActionMenu<SourceNodeActionId>
      position={sourceNodeMenuPosition}
      ariaLabel={t('管理来源目录')}
      title={sourceNodeActionTarget.title}
      items={(Object.entries(SOURCE_NODE_ACTION_DETAILS) as Array<[SourceNodeActionId, (typeof SOURCE_NODE_ACTION_DETAILS)[SourceNodeActionId]]>).map(([action, details]) => ({
        action,
        label: t(details.label),
        description: t(details.description),
        icon: details.icon,
        disabled: sourceNodeActionBusy !== null || (action === 'regenerate-cover' && !sourceNodeActionTarget.representativeResourceId)
      }))}
      returnFocusTo={sourceNodeMenuAnchor}
      onClose={() => { setSourceNodeMenuPosition(null); setSourceNodeActionTarget(null); }}
      onSelect={(action) => { void invokeSourceNodeAction(action); }}
    /> : null}

    {canManage && resourceActionTarget ? <ContextActionMenu<ResourceCardActionId>
      position={resourceMenuPosition}
      ariaLabel={t('管理可读资源')}
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
    <SourceNodeMetadataEditor
      bookId={book.id}
      book={book}
      entry={sourceNodeEditorTarget}
      fallbackCoverUrl={resources.find((resource) => resource.id === sourceNodeEditorTarget?.representativeResourceId)?.coverUrl ?? book.coverUrl}
      onClose={() => setSourceNodeEditorTarget(null)}
      onSaved={() => setContentsRevision((value) => value + 1)}
    />
    <SourceNodeMetadataRecognitionDialog bookId={book.id} entry={sourceNodeRecognitionTarget} onClose={() => setSourceNodeRecognitionTarget(null)} onSaved={() => setContentsRevision((value) => value + 1)} />
    <MetadataLookupModal book={book} currentResourceId={metadataResourceId ?? activeResource?.id ?? null} fixedScope={metadataResourceId ? 'resource' : null} open={metadataLookupOpen} onClose={() => { setMetadataLookupOpen(false); setMetadataResourceId(null); }} onApplied={refresh} />
    <KindleSendModal book={book} open={kindleOpen} preferredResourceId={activeResource?.id ?? null} onClose={() => setKindleOpen(false)} />
  </div>;
}
