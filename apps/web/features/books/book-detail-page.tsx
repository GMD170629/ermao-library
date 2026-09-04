'use client';

import { ArrowLeft, BookOpen, CheckCircle2, Edit3, Ellipsis, Headphones, ImagePlus, Images, LoaderCircle, RefreshCw, ScanSearch, Send, Sparkles, Trash2, X, type LucideIcon } from 'lucide-react';
import Link from 'next/link';
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
import { useAudioPlayback } from '../audio/public';
import {
  continueSourceImport,
  waitForImportTask
} from '../import-tasks/public';
import {
  deleteResourceSource,
  fetchBook,
  fetchBookContents,
  fetchResourceDetail,
  regenerateResourceCover,
  regenerateSourceNodeCover,
  updateResource,
  updateBookReadingStatus,
  uploadResourceCover
} from './api/client';
import { KindleSendModal } from './kindle-send-modal';
import { MetadataLookupModal } from './metadata-lookup-modal';
import {
  allVisibleResources,
  bookDetailHref,
  bookDetailReturnHref,
  librarySeriesHref,
  libraryTagHref,
  resourcePageFromQuery,
  selectedResourceForBook,
  singleReadableResourceForBook
} from './book-detail';
import { resourceDetailPageSize, type ResourceDetailPage } from './model/resource-detail';
import type { BookContentLayout, BookContentSort, BookContentsPage } from './model/book-contents';
import type { BookContentEntry } from './model/book-contents';
import { currentPositionLabel } from './model/current-position-label';
import { latestLocalV5Progress, localV5ProgressPercent } from './local-reader-progress';
import { getReaderRuntime } from '../../lib/reader';
import { currentReaderServerIdentity } from '../../lib/reader/v5-storage';
import { READER_V5_PROGRESS_CHANGED_EVENT } from '../../lib/reader/v5-sync-coordinator';
import { parseReaderV5PositionReport, type ReaderV5ProgressRecord } from '../../lib/reader/v5-wire';
import { BookContentBrowser } from './ui/book-content-browser';
import { ResourceDetailView } from './ui/resource-detail-view';
import { SourceNodeMetadataEditor, SourceNodeMetadataRecognitionDialog } from './ui/source-node-metadata-dialogs';
import { readableResourceActionIds, type ReadableResourceActionId } from './model/readable-resource-action-menu';
import { bookReadingStatus, resumeResourceForBook } from './model/book-action-menu';
import { BookActionController, type BookActionMenuRequest } from './ui/book-action-controller';

type ResourceForm = Readonly<{
  title: string;
  resourceIndex: string;
  description: string;
  publisher: string;
  publishedAt: string;
  language: string;
  isbn: string;
  identifier: string;
  narrator: string;
}>;

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

const RESOURCE_ACTION_DETAILS: Record<ReadableResourceActionId, { label: string; icon: LucideIcon; destructive?: boolean }> = {
  edit: { label: '编辑', icon: Edit3 },
  'upload-cover': { label: '上传封面', icon: ImagePlus },
  'regenerate-cover': { label: '重新生成封面', icon: RefreshCw },
  recognize: { label: '识别', icon: Sparkles },
  kindle: { label: '发送到 Kindle', icon: Send },
  delete: { label: '永久删除源文件', icon: Trash2, destructive: true }
};

function formForResource(resource: ReadableResourceView): ResourceForm {
  return {
    title: resource.title,
    resourceIndex: resource.resourceIndex === null ? '' : String(resource.resourceIndex),
    description: resource.description ?? '',
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
        title: form.title.trim(),
        resourceIndex: form.resourceIndex.trim() ? Number(form.resourceIndex) : null,
        description: form.description.trim() || null,
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
    <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>编辑可读资源</I18nText></h2><button type="button" onClick={onClose} aria-label={t('关闭')}><X size={20} /></button></div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="text-sm text-stone-600"><I18nText>卷标题</I18nText><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>卷号</I18nText><input type="number" step="any" value={form.resourceIndex} onChange={(event) => setForm({ ...form, resourceIndex: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5 tabular-nums" /></label>
        <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>简介</I18nText><textarea rows={4} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} className="mt-1.5 w-full resize-y rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>出版社</I18nText><input value={form.publisher} onChange={(event) => setForm({ ...form, publisher: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>出版时间</I18nText><input type="date" value={form.publishedAt} onChange={(event) => setForm({ ...form, publishedAt: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>语言</I18nText><input value={form.language} onChange={(event) => setForm({ ...form, language: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>ISBN</I18nText><input value={form.isbn} onChange={(event) => setForm({ ...form, isbn: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>标识符</I18nText><input value={form.identifier} onChange={(event) => setForm({ ...form, identifier: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        {resource.readerType === 'audio' ? <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>朗读者</I18nText><input value={form.narrator} onChange={(event) => setForm({ ...form, narrator: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label> : null}
      </div>
      <div className="mt-6 flex justify-end gap-2"><Button variant="secondary" onClick={onClose}><I18nText>取消</I18nText></Button><Button loading={saving} disabled={!form.title.trim() || (form.resourceIndex.trim() !== '' && !Number.isFinite(Number(form.resourceIndex)))} onClick={() => void save()}><I18nText>保存</I18nText></Button></div>
    </div>
  </div>;
}

export function BookDetailPage({ bookId }: { bookId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const feedback = useToast();
  const { t } = useI18n();
  const session = useAppSession();
  const audioPlayback = useAudioPlayback();
  const readerRuntime = getReaderRuntime();
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
  const [metadataLookupOpen, setMetadataLookupOpen] = useState(false);
  const [metadataResourceId, setMetadataResourceId] = useState<string | null>(null);
  const [kindleOpen, setKindleOpen] = useState(false);
  const [kindleResourceId, setKindleResourceId] = useState<string | null>(null);
  const [coverRevision, setCoverRevision] = useState(0);
  const [resourceEditorId, setResourceEditorId] = useState<string | null>(null);
  const [resourceMenuPosition, setResourceMenuPosition] = useState<ContextMenuPosition | null>(null);
  const [resourceMenuAnchor, setResourceMenuAnchor] = useState<HTMLButtonElement | null>(null);
  const [resourceActionTarget, setResourceActionTarget] = useState<ResourceCardActionTarget | null>(null);
  const [resourceActionBusy, setResourceActionBusy] = useState<ReadableResourceActionId | null>(null);
  const [sourceNodeActionTarget, setSourceNodeActionTarget] = useState<BookContentEntry | null>(null);
  const [sourceNodeMenuPosition, setSourceNodeMenuPosition] = useState<ContextMenuPosition | null>(null);
  const [sourceNodeMenuAnchor, setSourceNodeMenuAnchor] = useState<HTMLButtonElement | null>(null);
  const [sourceNodeActionBusy, setSourceNodeActionBusy] = useState<SourceNodeActionId | null>(null);
  const [sourceNodeEditorTarget, setSourceNodeEditorTarget] = useState<BookContentEntry | null>(null);
  const [sourceNodeRecognitionTarget, setSourceNodeRecognitionTarget] = useState<BookContentEntry | null>(null);
  const [readingStatusBusy, setReadingStatusBusy] = useState(false);
  const [bookActionRequest, setBookActionRequest] = useState<BookActionMenuRequest | null>(null);
  const [resourceDetail, setResourceDetail] = useState<ResourceDetailPage | null>(null);
  const [resourceDetailLoading, setResourceDetailLoading] = useState(false);
  const [resourceDetailError, setResourceDetailError] = useState('');
  const resourceCoverInputRef = useRef<HTMLInputElement>(null);
  const [coverUploadResourceId, setCoverUploadResourceId] = useState<string | null>(null);
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
  const [localProgressByResource, setLocalProgressByResource] = useState<Record<string, ReaderV5ProgressRecord>>({});
  const displayedResources = useMemo(() => resources.map((resource) => {
    const local = localProgressByResource[resource.id];
    return local ? { ...resource, progress: local.position.presentation.displayPercent } : resource;
  }), [localProgressByResource, resources]);
  const singleReadableResource = book ? singleReadableResourceForBook(book) : null;
  const selectedBookResource = book
    ? displayedResources.find((resource) => resource.id === selectedResourceForBook(book, requestedResourceId)?.id) ?? null
    : null;
  const requestedResource = requestedResourceId
    ? displayedResources.find((resource) => resource.id === requestedResourceId && resource.readable) ?? null
    : singleReadableResource
      ? displayedResources.find((resource) => resource.id === singleReadableResource.id) ?? null
      : null;
  const nestedNode = contentSourceNodeId
    ? contents?.currentNode?.sourceNodeId === contentSourceNodeId
      ? contents.currentNode
      : selectedContentNode?.sourceNodeId === contentSourceNodeId
        ? selectedContentNode
        : null
    : null;
  const nestedResources = nestedNode ? (contents?.currentResourceIds ?? []).flatMap((id) => {
    const resource = displayedResources.find((candidate) => candidate.id === id);
    return resource ? [resource] : [];
  }) : [];
  const activeResource = nestedNode
    ? nestedResources.find((resource) => resource.progress > 0 && resource.progress < 100)
      ?? nestedResources.find((resource) => resource.progress < 100)
      ?? nestedResources[0]
      ?? null
    : selectedBookResource;
  const serverResumeResource = book ? resumeResourceForBook(book) : null;
  const latestLocalProgress = latestLocalV5Progress(Object.values(localProgressByResource));
  const bookResumeResource = serverResumeResource
    ? displayedResources.find((resource) => resource.id === latestLocalProgress?.resourceId)
      ?? displayedResources.find((resource) => resource.id === serverResumeResource.id)
      ?? serverResumeResource
    : displayedResources.find((resource) => resource.id === latestLocalProgress?.resourceId) ?? null;
  const bookCopy = bookResumeResource ? consumptionCopy(bookResumeResource.readerType) : null;
  useEffect(() => {
    const userId = session?.user?.id;
    if (!book || !userId) { setLocalProgressByResource({}); return undefined; }
    let active = true;
    const readableResources = book.resources.filter((resource) => !resource.hidden && resource.readable);
    const applyLocalProgress = (records: ReaderV5ProgressRecord[]) => {
      if (active) setLocalProgressByResource((current) => {
        const next = { ...current };
        records.forEach((record) => {
          const previous = next[record.resourceId];
          if (!previous || previous.capturedAtEpochMillis <= record.capturedAtEpochMillis) next[record.resourceId] = record;
        });
        return next;
      });
    };
    void readerRuntime.storage.getClientId().then(async (clientId) => {
      const records = await Promise.all(readableResources.map(async (resource) => readerRuntime.storage.getV5Progress({
        serverIdentity: currentReaderServerIdentity(),
        userId,
        clientId,
        bookId: book.id,
        resourceId: resource.id
      })));
      applyLocalProgress(records.filter((record): record is ReaderV5ProgressRecord => record !== null));
    }).catch(() => { if (active) setLocalProgressByResource({}); });

    const handleProgressChanged = (event: Event) => {
      if (!(event instanceof CustomEvent)) return;
      const detail = event.detail as unknown;
      if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return;
      const value = detail as Record<string, unknown>;
      const position = parseReaderV5PositionReport(value.position);
      if (!position || value.userId !== userId || value.bookId !== book.id || typeof value.resourceId !== 'string'
        || typeof value.clientId !== 'string' || typeof value.serverIdentity !== 'string' || typeof value.key !== 'string'
        || typeof value.mutationId !== 'string' || typeof value.capturedAtEpochMillis !== 'number'
        || !Number.isSafeInteger(value.capturedAtEpochMillis)) return;
      const revision = typeof value.revision === 'number' && Number.isSafeInteger(value.revision) && value.revision >= 0
        ? value.revision
        : 0;
      const record: ReaderV5ProgressRecord = {
        serverIdentity: value.serverIdentity,
        userId,
        clientId: value.clientId,
        bookId: book.id,
        resourceId: value.resourceId,
        key: value.key,
        schemaVersion: 5,
        mutationId: value.mutationId,
        revision,
        capturedAtEpochMillis: value.capturedAtEpochMillis,
        position
      };
      setLocalProgressByResource((current) => {
        const previous = current[record.resourceId];
        if (previous && previous.capturedAtEpochMillis > record.capturedAtEpochMillis) return current;
        return { ...current, [record.resourceId]: record };
      });
    };
    window.addEventListener(READER_V5_PROGRESS_CHANGED_EVENT, handleProgressChanged);
    return () => {
      active = false;
      window.removeEventListener(READER_V5_PROGRESS_CHANGED_EVENT, handleProgressChanged);
    };
  }, [book, readerRuntime.storage, session?.user?.id]);
  const requestedLocalPresentation = requestedResource
    ? localProgressByResource[requestedResource.id]?.position.presentation ?? null
    : null;
  const localResumePresentation = bookResumeResource
    ? localProgressByResource[bookResumeResource.id]?.position.presentation ?? null
    : null;
  const displayedResourceDetail = resourceDetail && requestedLocalPresentation
    ? {
        ...resourceDetail,
        progress: requestedLocalPresentation.displayPercent,
        currentHref: requestedLocalPresentation.currentHref,
        currentChapterIndex: requestedLocalPresentation.chapter?.index ?? null,
        currentChapterTitle: requestedLocalPresentation.chapter?.title ?? null,
        currentChapterSortOrder: null,
        currentPageNumber: requestedLocalPresentation.page?.number ?? null
      }
    : resourceDetail;
  const bookProgress = book?.completed
    ? 100
    : localV5ProgressPercent(book?.continueResourceProgress ?? bookResumeResource?.progress ?? 0, latestLocalProgress);
  const bookStatus = book ? bookReadingStatus(book) : 'UNREAD';

  const playAudioResource = (resource: ReadableResourceView, assetId?: string, chapterTitle?: string) => {
    if (!book) return;
    void audioPlayback.loadResource(resource.id, {
      autoplay: true,
      assetId,
      summary: {
        resourceId: resource.id,
        bookId: book.id,
        title: book.title,
        author: book.author || null,
        coverUrl: resource.coverUrl || book.coverUrl || null,
        resourceTitle: resource.title || null,
        narrator: resource.narrator,
        chapterTitle: chapterTitle || null
      }
    });
  };

  const consumeBook = () => {
    if (!bookResumeResource?.readable) return;
    if (bookResumeResource.readerType === 'audio') {
      playAudioResource(bookResumeResource);
      return;
    }
    router.push(readerHref(bookResumeResource));
  };

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
    if (!book || (status !== 'UNREAD' && status !== 'FINISHED')) return;
    setReadingStatusBusy(true);
    try {
      await updateBookReadingStatus(book.id, status);
      await refresh();
      feedback.success(t(status === 'FINISHED' ? '已标记为已读' : '已标记为未读'));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('阅读状态更新失败'));
    } finally {
      setReadingStatusBusy(false);
    }
  };

  const openBookMenu = (anchor: HTMLButtonElement) => {
    if (!book) return;
    const bounds = anchor.getBoundingClientRect();
    setBookActionRequest({
      target: { id: book.id, title: book.title, status: bookStatus },
      position: { x: bounds.left + bounds.width / 2, y: bounds.bottom + 6 },
      horizontalAlign: 'center',
      anchor,
      book
    });
  };

  const openResourceMenu = (resource: ReadableResourceView, anchor: HTMLButtonElement) => {
    const bounds = anchor.getBoundingClientRect();
    setResourceActionTarget({ resourceId: resource.id, title: resource.title, assetCount: resource.assets.length });
    setResourceMenuAnchor(anchor);
    setResourceMenuPosition({ x: bounds.right, y: bounds.bottom + 6 });
  };

  const invokeResourceAction = async (action: ReadableResourceActionId) => {
    const target = resourceActionTarget;
    if (!book || !target) return;
    setResourceMenuPosition(null);
    setResourceActionTarget(null);
    if (action === 'edit') {
      setResourceEditorId(target.resourceId);
      return;
    }
    if (action === 'upload-cover') {
      setCoverUploadResourceId(target.resourceId);
      resourceCoverInputRef.current?.click();
      return;
    }
    if (action === 'recognize') {
      setMetadataResourceId(target.resourceId);
      setMetadataLookupOpen(true);
      return;
    }
    if (action === 'kindle') {
      setKindleResourceId(target.resourceId);
      setKindleOpen(true);
      return;
    }
    if (action === 'delete') {
      const confirmed = await feedback.confirm({
        title: '永久删除源文件',
        description: t('将永久删除“{value0}”关联的 {value1} 个源文件，此操作无法恢复。', { value0: target.title, value1: target.assetCount }),
        confirmLabel: '永久删除',
        tone: 'danger',
        confirmationText: target.title
      });
      if (!confirmed) return;
    }
    setResourceActionBusy(action);
    try {
      if (action === 'regenerate-cover') {
        const result = await regenerateResourceCover(book.id, target.resourceId);
        if (!result.updatedResourceIds.includes(target.resourceId)) {
          const skipped = result.skipped.map((item) => `${item.resourceId}: ${item.reason}`).join('；');
          feedback.error(t('封面更新失败，请稍后重试'), skipped || undefined);
          return;
        }
        setCoverRevision(Date.now());
        feedback.success(t('封面已重新生成'));
      } else if (action === 'delete') {
        await deleteResourceSource(book.id, target.resourceId, target.title);
        feedback.success(t('源文件已永久删除'));
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
        const result = await regenerateSourceNodeCover(book.id, target.sourceNodeId);
        const skipped = result.skipped.map((item) => `${item.resourceId}: ${item.reason}`).join('；');
        if (!result.sourceNodeUpdated || result.updatedResourceIds.length === 0) {
          feedback.error(t('封面更新失败，请稍后重试'), skipped || t('该来源目录还没有可用于生成封面的可读资源'));
          return;
        }
        setCoverRevision(Date.now());
        if (result.skipped.length > 0) {
          feedback.info(
            t('已处理 {value0} 本图书的封面{value1}', {
              value0: result.updatedResourceIds.length,
              value1: t('，跳过 {value0} 本', { value0: result.skipped.length })
            }),
            skipped
          );
        } else {
          feedback.success(t('封面已重新生成'));
        }
      } else {
        const requestResult = await continueSourceImport(target.sourceNodeId);
        feedback.success(t('已加入重新扫描队列'));
        if (requestResult.taskId) {
          const task = await waitForImportTask(requestResult.taskId);
          if (task?.state === 'FAILED') {
            throw new Error(task.errorSummary ?? t('重新扫描失败'));
          }
        }
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

  const seriesName = book.seriesName?.trim() ?? '';
  const tags = [...new Set(book.tags.map((tag) => tag.trim()).filter(Boolean))];
  const hasBookMetadata = Boolean(seriesName || tags.length > 0);

  return <div className="w-full">
    <button type="button" onClick={() => router.push(returnHref)} className="mb-6 inline-flex items-center gap-2 text-sm text-stone-600 hover:text-stone-950"><ArrowLeft size={17} /><I18nText>返回全部图书</I18nText></button>
    <section className="rounded-[22px] border border-[#f1ddd3] bg-[#fffaf7] p-5 sm:p-6">
      <div className="grid gap-6 lg:grid-cols-[150px_minmax(0,1fr)_230px]">
        <Cover book={{ ...book, coverUrl: coverRevision > 0 && book.coverUrl ? `${book.coverUrl}${book.coverUrl.includes('?') ? '&' : '?'}v=${coverRevision}` : book.coverUrl }} className="mx-auto aspect-[2/3] w-24 max-w-[150px] rounded-xl shadow-md sm:w-[150px] lg:mx-0" size="small" priority />
        <div className="flex min-w-0 flex-col py-1">
          {book.completed ? <span className="inline-flex w-fit items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"><CheckCircle2 size={14} /><I18nText>已完成</I18nText></span> : null}
          <h1 data-i18n-skip className="mt-2 line-clamp-2 text-3xl font-semibold leading-[1.15] tracking-tight text-stone-950 sm:text-[34px]">{book.title}</h1>
          <p data-i18n-skip className="mt-3 text-base text-stone-600">{book.author}</p>
          {hasBookMetadata ? <div className="mt-4 flex min-w-0 flex-col items-start gap-2 text-sm sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4 sm:gap-y-2">
            {seriesName ? <span className="flex min-w-0 max-w-full items-center gap-2">
              <span className="shrink-0 text-stone-400"><I18nText>系列</I18nText></span>
              <Link
                href={librarySeriesHref(seriesName)}
                prefetch={false}
                aria-label={t('查看系列“{value0}”中的图书', { value0: seriesName })}
                data-i18n-skip
                className="max-w-full truncate rounded-md font-medium text-stone-700 outline-none transition hover:text-[#D7462B] hover:underline focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
                title={seriesName}
              >{seriesName}</Link>
            </span> : null}
            {tags.length > 0 ? <div className="flex max-w-full flex-wrap items-center gap-2 sm:border-l sm:border-stone-200 sm:pl-4">
              {tags.map((tag) => <Link
                key={tag}
                href={libraryTagHref(tag)}
                prefetch={false}
                aria-label={t('查看标签“{value0}”下的图书', { value0: tag })}
                data-i18n-skip
                className="inline-flex min-h-7 items-center rounded-lg border border-[#efd7cc] bg-[#fff7f3] px-2.5 py-1 text-xs font-medium leading-4 text-stone-600 outline-none transition hover:border-[#efb7a5] hover:bg-[#fff0ea] hover:text-[#D7462B] focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
              >{tag}</Link>)}
            </div> : null}
          </div> : null}
          {book.description ? <p data-i18n-skip className={hasBookMetadata ? "mt-4 line-clamp-3 max-w-3xl whitespace-pre-line text-sm leading-7 text-stone-600" : "mt-5 line-clamp-3 max-w-3xl whitespace-pre-line text-sm leading-7 text-stone-600"}>{book.description}</p> : <p className={hasBookMetadata ? "mt-4 text-sm text-stone-400" : "mt-5 text-sm text-stone-400"}><I18nText>暂无简介</I18nText></p>}
          {bookCopy ? <div className="mt-7 max-w-3xl">
            <div className="flex items-center gap-4"><span className="shrink-0 text-sm font-medium text-stone-700">{t(bookCopy.progress)}</span><div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-stone-200"><div className="h-full rounded-full bg-[#ff4f26]" style={{ width: `${bookProgress}%` }} /></div><span className="w-14 text-right text-sm font-medium tabular-nums text-stone-700">{Math.round(bookProgress)}%</span></div>
          <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm"><span className="font-medium text-stone-700">{t(bookCopy.position)}</span><span data-i18n-skip className="text-stone-800">{bookResumeResource ? currentPositionLabel(bookResumeResource, requestedResource?.id === bookResumeResource.id ? displayedResourceDetail : null, t, localResumePresentation) : ''}</span></div>
          </div> : null}
          {error ? <p className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
        </div>
        <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end lg:col-start-2 xl:col-start-3 xl:flex-col xl:justify-end">
          {bookCopy ? <Button disabled={!bookResumeResource} loading={bookResumeResource?.readerType === 'audio' && audioPlayback.pendingResourceId === bookResumeResource.id && !audioPlayback.loadError} loadingText="正在准备有声书…" icon={bookResumeResource?.readerType === 'audio' ? Headphones : bookResumeResource?.readerType === 'comic' ? Images : BookOpen} onClick={consumeBook} className="!h-12 !min-h-12 w-full !rounded-xl !bg-[#ff4f26] !px-8 !text-base !text-white hover:!bg-[#e84420]">{t(bookProgress > 0 ? bookCopy.resume : bookCopy.start)}</Button> : null}
          <div className="flex w-full gap-2">
            {bookCopy ? <Select value={bookStatus} options={[{ value: 'READING', label: '在读', disabled: bookStatus !== 'READING' }, { value: 'UNREAD', label: '未读' }, { value: 'FINISHED', label: '已读' }]} onChange={(status) => void changeReadingStatus(status)} ariaLabel={t('图书阅读状态')} disabled={readingStatusBusy} className="min-w-0 flex-1" /> : null}
            <button type="button" onClick={(event) => openBookMenu(event.currentTarget)} onContextMenu={(event) => { event.preventDefault(); openBookMenu(event.currentTarget); }} className="ml-auto flex h-11 w-12 shrink-0 items-center justify-center rounded-xl border border-[#ead8cf] bg-white/80 text-stone-600 transition hover:bg-white hover:text-stone-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-200" aria-label={t('管理图书 {value0}', { value0: book.title })} aria-haspopup="menu"><Ellipsis size={20} /></button>
          </div>
        </div>
      </div>
    </section>

    <input ref={resourceCoverInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; const resourceId = coverUploadResourceId; event.currentTarget.value = ''; if (!file || !resourceId) return; setResourceActionBusy('upload-cover'); void uploadResourceCover(book.id, resourceId, file).then(async () => { setCoverRevision(Date.now()); await refresh(); setContentsRevision((value) => value + 1); feedback.success(t('封面已上传')); }).catch((reason) => feedback.error(reason instanceof Error ? reason.message : t('操作失败'))).finally(() => { setResourceActionBusy(null); setCoverUploadResourceId(null); }); }} />

    {requestedResource ? <ResourceDetailView
      resource={requestedResource}
      detail={displayedResourceDetail}
      loading={resourceDetailLoading}
      error={resourceDetailError}
      requestedPage={requestedResourcePage}
      onBack={singleReadableResource ? null : () => updateResourceLocation(null)}
      onPageChange={(page) => updateResourceLocation(requestedResource.id, page)}
      onPlayAudio={(assetId, chapterTitle) => playAudioResource(requestedResource, assetId, chapterTitle)}
    /> : <BookContentBrowser
      book={book}
      contents={contents}
      resources={displayedResources}
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
      onManageResource={openResourceMenu}
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
        disabled: sourceNodeActionBusy !== null
      }))}
      returnFocusTo={sourceNodeMenuAnchor}
      onClose={() => { setSourceNodeMenuPosition(null); setSourceNodeActionTarget(null); }}
      onSelect={(action) => { void invokeSourceNodeAction(action); }}
    /> : null}

    {resourceActionTarget ? <ContextActionMenu<ReadableResourceActionId>
      position={resourceMenuPosition}
      ariaLabel={t('管理可读资源')}
      title={resourceActionTarget.title}
      items={readableResourceActionIds({ canManage, kindleSendAvailable: resources.find((resource) => resource.id === resourceActionTarget.resourceId)?.kindleSendAvailable === true }).map((action) => ({
        action,
        label: t(RESOURCE_ACTION_DETAILS[action].label),
        icon: RESOURCE_ACTION_DETAILS[action].icon,
        destructive: RESOURCE_ACTION_DETAILS[action].destructive,
        disabled: resourceActionBusy !== null,
        separatorBefore: action === 'delete'
      }))}
      returnFocusTo={resourceMenuAnchor}
      onClose={() => { setResourceMenuPosition(null); setResourceActionTarget(null); }}
      onSelect={(action) => { void invokeResourceAction(action); }}
    /> : null}

    <BookActionController
      request={bookActionRequest}
      canManage={canManage}
      onRequestClose={() => setBookActionRequest(null)}
      onChanged={async (nextBook) => {
        if (nextBook) setBook(nextBook);
        else await refresh();
        setCoverRevision(Date.now());
        setContentsRevision((value) => value + 1);
      }}
      onDeleted={() => { router.push(returnHref); }}
    />

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
    <KindleSendModal book={book} open={kindleOpen} preferredResourceId={kindleResourceId ?? activeResource?.id ?? null} onClose={() => { setKindleOpen(false); setKindleResourceId(null); }} />
  </div>;
}
