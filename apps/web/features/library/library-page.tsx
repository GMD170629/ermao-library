'use client';

import { BookmarkPlus, BookOpen, ChevronLeft, ChevronRight, Filter, List, Loader2, Plus, Search, Trash2, UploadCloud, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import { BookshelfCollection } from '../../components/book/bookshelf';
import { BookTable } from '../../components/book/book-table';
import { MobileNavigationTrigger } from '../../components/layout/mobile-navigation';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useToast } from '../../components/ui/feedback';
import { Select } from '../../components/ui/select';
import {
  fetchLibraryWorksPage,
  type LibraryWorkSummary,
  type ManagementWorkSummary
} from './api/works';
import { LibraryBatchContextMenu, LibraryBatchDialog, type LibraryBatchAction } from './library-batch-actions';
import { canUseLibraryBatchAction } from './model/library-batch-action';
import {
  applicableSmartFilterRules,
  parseSmartFilterRules,
  serializableSmartFilterRules
} from './model/smart-filter-rules';
import { SmartFilterBuilder, type SmartFilterField, type SmartFilterRules } from './smart-filter-builder';
import { UploadBookDialog } from './upload-book-dialog';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { currentUserId, saveAccountPreferences, userDevicePreferenceKey } from '../../lib/user-preferences';
import {
  DEFAULT_LIBRARY_SORT_PREFERENCE,
  defaultLibrarySortDirection,
  librarySortPreferenceFromRoute,
  parseLibrarySortPreference,
  parseLibrarySortPreferenceValue,
  resolveLibrarySortPreference,
  type LibrarySort,
  type LibrarySortDirection
} from './model/library-sort-preference';

type FilterSchemaResponse = {
  ok: boolean;
  data?: { fields: SmartFilterField[]; maxConditions: number };
  error?: { message: string };
};

const formatOptions = [
  { value: '全部', label: '全部' },
  { value: 'ebook', label: '电子书' },
  { value: 'COMIC', label: '漫画' },
  { value: 'AUDIOBOOK', label: '有声书' }
];

const statusOptions = [
  { value: '全部', label: '全部状态' },
  { value: 'UNREAD', label: '未开始' },
  { value: 'READING', label: '进行中' },
  { value: 'FINISHED', label: '已完成' }
];

const pageSizeOptions = [
  { value: '20', label: '20 本/页' },
  { value: '50', label: '50 本/页' },
  { value: '100', label: '100 本/页' },
  { value: '500', label: '500 本/页' },
  { value: 'all', label: '全部显示' }
];

const validStatuses = new Set(statusOptions.map((option) => option.value));
const DEFAULT_LIBRARY_PAGE_SIZE = 20;
const BROWSE_LIBRARY_PAGE_SIZE = 50;
const LIBRARY_SORT_DEVICE_PREFERENCE_KEY = 'shuku.library.sort:v1';

function routeStatus(value: string | null) {
  if (value === 'WANT') return 'UNREAD';
  return value && validStatuses.has(value) ? value : '全部';
}

export function LibraryPage() {
  const { t: i18nAttribute } = useAttributeI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchParamString = searchParams.toString();
  const seriesNameFilter = searchParams.get('seriesName')?.trim() ?? '';
  const rawFacetKind = searchParams.get('facetKind')?.trim().toUpperCase() ?? '';
  const facetKindFilter = rawFacetKind === 'SERIES' || rawFacetKind === 'AUTHOR'
    ? rawFacetKind
    : '';
  const facetIdFilter = facetKindFilter ? searchParams.get('facetId')?.trim() ?? '' : '';
  const facetNameFilter = facetIdFilter ? searchParams.get('facetName')?.trim() ?? '' : '';
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [formatFilter, setFormatFilter] = useState('全部');
  const [statusFilter, setStatusFilter] = useState(() => routeStatus(searchParams.get('status')));
  const initialRouteSort = librarySortPreferenceFromRoute(searchParams.get('sort'), searchParams.get('sortDirection'));
  const initialSortPreference = initialRouteSort ?? DEFAULT_LIBRARY_SORT_PREFERENCE;
  const [sort, setSort] = useState<LibrarySort>(initialSortPreference.sort);
  const [sortDirection, setSortDirection] = useState<LibrarySortDirection>(initialSortPreference.direction);
  const [sortPreferenceLoaded, setSortPreferenceLoaded] = useState(initialRouteSort !== null);
  const [search, setSearch] = useState(() => searchParams.get('search') ?? '');
  const [smartFilterRules, setSmartFilterRules] = useState<SmartFilterRules>(() => parseSmartFilterRules(searchParams.get('filters')));
  const [smartFilterFields, setSmartFilterFields] = useState<SmartFilterField[]>([]);
  const [filterSchemaLoading, setFilterSchemaLoading] = useState(false);
  const [filterSchemaLoaded, setFilterSchemaLoaded] = useState(false);
  const [books, setBooks] = useState<LibraryWorkSummary[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(String(DEFAULT_LIBRARY_PAGE_SIZE));
  const [meta, setMeta] = useState({ total: 0, pageSize: DEFAULT_LIBRARY_PAGE_SIZE, totalPages: 1 });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [canManageSystem, setCanManageSystem] = useState(false);
  const [authorizationLoaded, setAuthorizationLoaded] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<LibraryWorkSummary | null>(null);
  const [deleteSource, setDeleteSource] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [selectedWorkIds, setSelectedWorkIds] = useState<string[]>([]);
  const [batchDialogAction, setBatchDialogAction] = useState<LibraryBatchAction | null>(null);
  const [batchContextPosition, setBatchContextPosition] = useState<{ x: number; y: number } | null>(null);
  const [smartShelfOpen, setSmartShelfOpen] = useState(false);
  const [smartShelfName, setSmartShelfName] = useState('');
  const [smartShelfSaving, setSmartShelfSaving] = useState(false);
  const loadMoreRef = useRef<HTMLDivElement>(null);
  const requestedScopeRef = useRef('');
  const requestedReloadKeyRef = useRef(reloadKey);
  const rememberedSortPreferenceRef = useRef(initialSortPreference);
  const toast = useToast();
  const applicableRules = useMemo(
    () => applicableSmartFilterRules(smartFilterRules),
    [smartFilterRules]
  );
  const incompleteSmartFilterCount = smartFilterRules.conditions.length - applicableRules.conditions.length;
  const smartFilterQuery = useMemo(() => applicableRules.conditions.length > 0 ? JSON.stringify(serializableSmartFilterRules(applicableRules)) : '', [applicableRules]);
  const isSeriesFacet = facetKindFilter === 'SERIES' && Boolean(facetIdFilter);
  const isAuthorFacet = facetKindFilter === 'AUTHOR' && Boolean(facetIdFilter);
  const queryBase = useMemo(() => {
    const params = new URLSearchParams();
    if (search.trim()) params.set('search', search.trim());
    if (formatFilter !== '全部') params.set('type', formatFilter);
    if (statusFilter !== '全部') params.set('status', statusFilter);
    if (seriesNameFilter) params.set('seriesName', seriesNameFilter);
    if (facetKindFilter && facetIdFilter) {
      params.set('facetKind', facetKindFilter);
      params.set('facetId', facetIdFilter);
    }
    if (smartFilterQuery) params.set('filters', smartFilterQuery);
    params.set('visibility', 'active');
    params.set('sort', isSeriesFacet ? 'series_index' : isAuthorFacet ? 'updated' : sort);
    params.set('sortDirection', isSeriesFacet ? 'asc' : isAuthorFacet ? 'desc' : sortDirection);
    return params.toString();
  }, [facetIdFilter, facetKindFilter, formatFilter, isAuthorFacet, isSeriesFacet, search, seriesNameFilter, smartFilterQuery, sort, sortDirection, statusFilter]);
  const requestPageSize = view === 'grid'
    ? String(BROWSE_LIBRARY_PAGE_SIZE)
    : pageSize === 'all'
    ? '0'
    : pageSize;
  const requestScope = `${queryBase}&pageSize=${requestPageSize}&view=${view}`;

  useEffect(() => {
    setPage(1);
    setBooks([]);
  }, [requestScope]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetch('/api/auth/preferences', { cache: 'no-store', credentials: 'same-origin', signal: controller.signal })
        .then((response) => response.json())
        .catch(() => null),
      fetch('/api/auth/me', { cache: 'no-store', credentials: 'same-origin', signal: controller.signal })
        .then((response) => response.json())
        .catch(() => null)
    ]).then(([preferencesPayload, sessionPayload]) => {
      const accountPreferences = preferencesPayload?.ok ? preferencesPayload.data?.preferences : null;
      const accountView = accountPreferences?.['library.view'];
      let deviceView = null;
      try {
        deviceView = window.localStorage.getItem(userDevicePreferenceKey('shuku.library.view'));
      } catch {
        deviceView = null;
      }
      const savedView = accountView ?? deviceView;
      if (savedView === 'grid' || savedView === 'list') setView(savedView);
      let deviceSortPreference = null;
      try {
        const stored = window.localStorage.getItem(userDevicePreferenceKey(LIBRARY_SORT_DEVICE_PREFERENCE_KEY));
        deviceSortPreference = stored ? parseLibrarySortPreferenceValue(JSON.parse(stored) as unknown) : null;
      } catch {
        deviceSortPreference = null;
      }
      const currentRouteParameters = new URLSearchParams(window.location.search);
      const routePreference = librarySortPreferenceFromRoute(
        currentRouteParameters.get('sort'),
        currentRouteParameters.get('sortDirection')
      );
      const rememberedSortPreference = resolveLibrarySortPreference({
        route: null,
        account: parseLibrarySortPreference(
          accountPreferences?.['library.sort'],
          accountPreferences?.['library.sortDirection']
        ),
        device: deviceSortPreference
      });
      rememberedSortPreferenceRef.current = rememberedSortPreference;
      const activeSortPreference = routePreference ?? rememberedSortPreference;
      setSort(activeSortPreference.sort);
      setSortDirection(activeSortPreference.direction);
      setSortPreferenceLoaded(true);
      setCanManageSystem(Boolean(sessionPayload?.ok && sessionPayload.data?.authorization?.canManageSystem));
      setAuthorizationLoaded(true);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const routeParams = new URLSearchParams(searchParamString);
    setStatusFilter(routeStatus(routeParams.get('status')));
    const activeSortPreference = librarySortPreferenceFromRoute(routeParams.get('sort'), routeParams.get('sortDirection'))
      ?? rememberedSortPreferenceRef.current;
    setSort(activeSortPreference.sort);
    setSortDirection(activeSortPreference.direction);
    setSearch(routeParams.get('search') ?? '');
    setUploadDialogOpen(authorizationLoaded && canManageSystem && routeParams.get('upload') === '1');
  }, [authorizationLoaded, canManageSystem, searchParamString]);

  useEffect(() => {
    if (!filtersOpen || filterSchemaLoaded) return;
    let active = true;
    setFilterSchemaLoading(true);
    fetch('/api/library/filter-schema')
      .then((response) => response.json() as Promise<FilterSchemaResponse>)
      .then((payload) => {
        if (!active) return;
        if (!payload.ok) throw new Error(payload.error?.message ?? '读取筛选维度失败');
        setSmartFilterFields(payload.data?.fields ?? []);
        setFilterSchemaLoaded(true);
      })
      .catch((reason) => {
        if (!active) return;
        toast.error('读取筛选维度失败', reason instanceof Error ? reason.message : '请稍后重试');
      })
      .finally(() => active && setFilterSchemaLoading(false));
    return () => { active = false; };
  }, [filterSchemaLoaded, filtersOpen, toast]);

  useEffect(() => {
    if (!sortPreferenceLoaded) return;
    let active = true;
    const scopeChanged = requestedScopeRef.current !== requestScope;
    const reloadChanged = requestedReloadKeyRef.current !== reloadKey;
    const requestedPage = scopeChanged || reloadChanged ? 1 : page;
    requestedScopeRef.current = requestScope;
    requestedReloadKeyRef.current = reloadKey;
    if (requestedPage !== page) setPage(requestedPage);

    const controller = new AbortController();
    setLoading(true);
    fetchLibraryWorksPage(
      queryBase,
      requestedPage,
      requestPageSize,
      view === 'grid' ? 'bookshelf' : 'management',
      controller.signal
    )
      .then((data) => {
        if (!active) return;
        if (requestedPage > data.totalPages && data.totalPages > 0) {
          setPage(data.totalPages);
          return;
        }
        const nextBooks = data.books;
        setBooks((current) => {
          if (view !== 'grid' || requestedPage <= 1) return nextBooks;
          const merged = new Map(current.map((book) => [book.id, book]));
          nextBooks.forEach((book) => merged.set(book.id, book));
          return Array.from(merged.values());
        });
        setMeta({
          total: data.total,
          pageSize: data.pageSize,
          totalPages: data.totalPages
        });
        setError('');
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : '读取书库失败');
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
      controller.abort();
    };
  }, [page, queryBase, reloadKey, requestPageSize, requestScope, sortPreferenceLoaded, view]);

  useEffect(() => {
    const sentinel = loadMoreRef.current;
    if (!sentinel || view !== 'grid' || loading || page >= meta.totalPages) return;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      setPage((current) => Math.min(meta.totalPages, current + 1));
    }, { rootMargin: '700px 0px' });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loading, meta.totalPages, page, view]);

  useEffect(() => {
    const visibleIds = new Set(books.map((book) => book.id));
    setSelectedWorkIds((current) => current.filter((id) => visibleIds.has(id)));
  }, [books]);

  const advancedFilterCount = [statusFilter !== '全部', seriesNameFilter, facetIdFilter].filter(Boolean).length + smartFilterRules.conditions.length;
  const pageTitle = facetNameFilter
    ? facetNameFilter
    : seriesNameFilter
    ? seriesNameFilter
    : statusFilter === 'UNREAD'
    ? '未开始'
    : statusFilter === 'READING'
      ? '进行中'
      : statusFilter === 'FINISHED'
        ? '已完成'
        : '全部图书';

  function updateView(nextView: 'grid' | 'list') {
    setBooks([]);
    setPage(1);
    setLoading(true);
    setView(nextView);
    if (nextView === 'grid') {
      setFiltersOpen(false);
      setSelectedWorkIds([]);
      setBatchContextPosition(null);
    }
    window.localStorage.setItem(userDevicePreferenceKey('shuku.library.view', currentUserId()), nextView);
    void saveAccountPreferences({ 'library.view': nextView }).catch(() => undefined);
  }

  function replaceRoute(mutator: (params: URLSearchParams) => void) {
    const params = new URLSearchParams(searchParams.toString());
    if (search.trim()) params.set('search', search.trim());
    else params.delete('search');
    mutator(params);
    const next = params.toString();
    router.replace(next ? `/library?${next}` : '/library', { scroll: false });
  }

  function updateStatus(nextStatus: string) {
    setStatusFilter(nextStatus);
    replaceRoute((params) => {
      if (nextStatus === '全部') params.delete('status');
      else params.set('status', nextStatus);
    });
  }

  function updateSort(nextSort: string, nextDirection: LibrarySortDirection) {
    const nextPreference = parseLibrarySortPreference(nextSort, nextDirection);
    if (!nextPreference) return;
    rememberedSortPreferenceRef.current = nextPreference;
    setSort(nextPreference.sort);
    setSortDirection(nextPreference.direction);
    try {
      window.localStorage.setItem(
        userDevicePreferenceKey(LIBRARY_SORT_DEVICE_PREFERENCE_KEY, currentUserId()),
        JSON.stringify(nextPreference)
      );
    } catch {
      // Account persistence still preserves the preference when device storage is unavailable.
    }
    void saveAccountPreferences({
      'library.sort': nextPreference.sort,
      'library.sortDirection': nextPreference.direction
    }).catch(() => undefined);
    replaceRoute((params) => {
      if (nextSort === DEFAULT_LIBRARY_SORT_PREFERENCE.sort) params.delete('sort');
      else params.set('sort', nextSort);
      if (nextDirection === defaultLibrarySortDirection(nextPreference.sort)) params.delete('sortDirection');
      else params.set('sortDirection', nextDirection);
    });
  }

  function openUploadDialog() {
    if (!canManageSystem) return;
    setUploadDialogOpen(true);
  }

  function clearUploadRoute() {
    if (searchParams.get('upload') !== '1') return;
    replaceRoute((params) => params.delete('upload'));
  }

  function closeUploadDialog() {
    setUploadDialogOpen(false);
    clearUploadRoute();
  }

  function openDeleteBook(book: LibraryWorkSummary) {
    setDeleteSource(false);
    setDeleteTarget(book);
  }

  async function deleteBook() {
    const book = deleteTarget;
    if (!book) return;
    setDeleting(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`/api/works/${book.id}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deleteSource })
      });
      const payload = (await response.json()) as { ok: boolean; data?: { failedFileDeletes?: Array<{ path: string; message: string }> }; error?: { message: string } };
      if (!payload.ok) throw new Error(payload.error?.message ?? '删除失败');
      setDeleteTarget(null);
      setMessage('已删除书库记录');
      const failedCount = payload.data?.failedFileDeletes?.length ?? 0;
      toast.success('已删除书库记录', failedCount > 0 ? `有 ${failedCount} 个文件未能删除，请检查系统日志` : deleteSource ? '关联的源文件已同步删除' : '来源文件已保留');
      setReloadKey((key) => key + 1);
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '删除失败';
      setError(nextError);
      toast.error('删除失败', nextError);
    } finally {
      setDeleting(false);
    }
  }

  function clearAdvancedFilters() {
    setStatusFilter('全部');
    setSmartFilterRules({ combinator: 'ALL', conditions: [] });
    replaceRoute((params) => {
      params.delete('status');
      params.delete('seriesName');
      params.delete('facetKind');
      params.delete('facetId');
      params.delete('facetName');
      params.delete('filters');
    });
  }

  function toggleSelection(bookId: string) {
    setSelectedWorkIds((current) => current.includes(bookId) ? current.filter((id) => id !== bookId) : [...current, bookId]);
  }

  function togglePageSelection(selected: boolean) {
    setSelectedWorkIds(selected ? books.map((book) => book.id) : []);
  }

  function openBatchAction(action: LibraryBatchAction) {
    if (!canUseLibraryBatchAction(action, canManageSystem)) return;
    setBatchContextPosition(null);
    setBatchDialogAction(action);
  }

  function finishBatchAction(nextMessage: string) {
    setMessage(nextMessage);
    setBatchDialogAction(null);
    setSelectedWorkIds([]);
    setReloadKey((key) => key + 1);
  }

  async function saveSmartShelf() {
    if (!smartShelfName.trim()) return;
    setSmartShelfSaving(true);
    try {
      const rules: Record<string, unknown> = {};
      if (search.trim()) rules.search = search.trim();
      if (statusFilter !== '全部') rules.statuses = [statusFilter];
      if (formatFilter !== '全部') rules.mediaKinds = [formatFilter === 'ebook' ? 'EBOOK' : formatFilter];
      if (applicableRules.conditions.length > 0) Object.assign(rules, serializableSmartFilterRules(applicableRules));
      const response = await fetch('/api/shelves', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: smartShelfName.trim(), description: '由书库筛选条件自动更新', kind: 'SMART', rules, pinned: true }) });
      const payload = await response.json() as { ok: boolean; error?: { message: string } };
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '保存智能书架失败');
      toast.success('智能书架已保存', '以后符合这些条件的图书会自动出现。');
      window.dispatchEvent(new Event('shuku:shelves-changed'));
      setSmartShelfOpen(false);
      setSmartShelfName('');
    } catch (reason) {
      toast.error('保存失败', reason instanceof Error ? reason.message : '保存智能书架失败');
    } finally { setSmartShelfSaving(false); }
  }

  return (
    <div>
      <header className="flex items-start justify-between gap-6">
        <div className="flex min-w-0 items-center gap-3 sm:gap-4">
          <MobileNavigationTrigger />
          <div className="flex min-w-0 items-baseline gap-3 sm:gap-4">
            <h1 className="truncate text-[30px] font-semibold leading-none tracking-[-0.035em] text-[#1E1D1B] sm:text-[44px]">{pageTitle}</h1>
            {!loading ? <span className="shrink-0 text-[13px] text-[#8A847E] sm:text-[15px]">{meta.total} <I18nText>本</I18nText></span> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => updateView(view === 'grid' ? 'list' : 'grid')}
            className="inline-flex h-11 items-center gap-2 rounded-xl px-3 text-sm font-medium text-[#625D58] transition hover:bg-black/[0.035] hover:text-[#2D2926] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
          >
            {view === 'grid' ? <List size={17} strokeWidth={1.8} /> : <BookOpen size={17} strokeWidth={1.8} />}
            {view === 'grid' ? <I18nText>管理图书</I18nText> : <I18nText>返回书架</I18nText>}
          </button>
          {canManageSystem ? <button
            type="button"
            onClick={openUploadDialog}
            aria-label={i18nAttribute("上传读物")}
            title={i18nAttribute("上传读物")}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#FF4F2A] text-white transition hover:bg-[#E94320] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
          >
            <Plus size={22} strokeWidth={1.7} />
          </button> : null}
        </div>
      </header>

      {canManageSystem ? <UploadBookDialog
        open={uploadDialogOpen}
        onClose={closeUploadDialog}
        onImported={(nextMessage) => {
          setMessage(nextMessage);
          setError('');
          setReloadKey((key) => key + 1);
        }}
        onError={setError}
      /> : null}

      {deleteTarget ? (
        <div className="fixed inset-0 z-[90] flex items-end justify-center bg-[#241F1C]/35 p-0 backdrop-blur-[2px] md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={i18nAttribute("删除图书记录")}>
          <div className="w-full max-w-lg rounded-t-3xl border border-black/[0.08] bg-[#FFFEFC] p-5 shadow-[0_28px_80px_rgba(47,37,31,0.22)] md:rounded-3xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-[#25221F]"><I18nText>删除图书记录</I18nText></h2>
                <p className="mt-2 text-sm leading-6 text-[#6F6963]">{i18nAttribute('删除《{value0}》的书库记录和系统生成文件。你可以选择是否同时删除源文件。', { value0: deleteTarget.title })}</p>
              </div>
              <button type="button" disabled={deleting} onClick={() => setDeleteTarget(null)} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-[#77716B] hover:bg-black/[0.05] disabled:opacity-50" aria-label={i18nAttribute("关闭")}><X size={18} /></button>
            </div>
            <label className={cn('mt-5 flex cursor-pointer gap-3 rounded-2xl border p-4 transition', deleteSource ? 'border-red-200 bg-red-50' : 'border-black/[0.08] bg-black/[0.02] hover:bg-black/[0.04]')}>
              <input type="checkbox" checked={deleteSource} disabled={deleting} onChange={(event) => setDeleteSource(event.target.checked)} className="mt-0.5 h-4 w-4 accent-red-600" />
              <span>
                <span className="block text-sm font-semibold text-[#302C29]"><I18nText>同步删除源文件</I18nText></span>
                <span className="mt-1 block text-xs leading-5 text-[#77716B]"><I18nText>源文件将从监控或上传目录中永久删除；该操作无法恢复。</I18nText></span>
              </span>
            </label>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="secondary" disabled={deleting} onClick={() => setDeleteTarget(null)}><I18nText>取消</I18nText></Button>
              <Button type="button" variant="danger" icon={Trash2} loading={deleting} loadingText={i18nAttribute("删除中")} onClick={() => void deleteBook()}>{deleteSource ? i18nAttribute("删除记录和源文件") : i18nAttribute("删除记录")}</Button>
            </div>
          </div>
        </div>
      ) : null}

      {smartShelfOpen ? (
        <div className="fixed inset-0 z-[90] flex items-end justify-center bg-[#241F1C]/35 p-0 backdrop-blur-[2px] md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={i18nAttribute("保存智能书架")}>
          <div className="w-full max-w-md rounded-t-3xl bg-[#FFFEFC] p-6 shadow-2xl md:rounded-3xl">
            <div className="flex items-start justify-between gap-4"><div><h2 className="text-lg font-semibold text-[#2D2926]"><I18nText>保存为智能书架</I18nText></h2><p className="mt-1 text-sm leading-6 text-[#817B75]"><I18nText>保存当前搜索、类型、状态和标签条件，结果会随书库自动更新。</I18nText></p></div><button type="button" onClick={() => setSmartShelfOpen(false)}><X size={18} /></button></div>
            <label className="mt-5 block text-sm text-[#6F6963]"><I18nText>书架名称</I18nText><input autoFocus value={smartShelfName} onChange={(event) => setSmartShelfName(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-black/[0.1] bg-white px-4 outline-none focus:border-[#E8A18D]" placeholder={pageTitle === '全部图书' ? i18nAttribute("例如：近期科幻阅读") : pageTitle} /></label>
            <div className={cn('mt-4 rounded-xl px-4 py-3 text-xs leading-5', incompleteSmartFilterCount > 0 ? 'bg-amber-50 text-amber-800' : 'bg-black/[0.035] text-[#746E68]')}>{incompleteSmartFilterCount > 0 ? i18nAttribute("还有 {value0} 条条件没有填写完整，请返回补全后再保存。", { value0: incompleteSmartFilterCount }) : [search.trim() && `搜索“${search.trim()}”`, formatFilter !== '全部' && `类型：${formatOptions.find((item) => item.value === formatFilter)?.label}`, statusFilter !== '全部' && `状态：${statusOptions.find((item) => item.value === statusFilter)?.label}`, applicableRules.conditions.length > 0 && `${applicableRules.conditions.length} 条${applicableRules.combinator === 'ALL' ? '全部匹配' : '任一匹配'}规则`].filter(Boolean).join(' · ') || i18nAttribute("当前没有额外条件，将包含全部可见图书")}</div>
            <div className="mt-6 flex justify-end gap-2"><Button variant="secondary" onClick={() => setSmartShelfOpen(false)}><I18nText>取消</I18nText></Button><Button icon={BookmarkPlus} loading={smartShelfSaving} disabled={!smartShelfName.trim() || incompleteSmartFilterCount > 0} onClick={() => void saveSmartShelf()}><I18nText>保存书架</I18nText></Button></div>
          </div>
        </div>
      ) : null}

      {view === 'list' ? <div className="mt-8 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
          <label className="flex h-12 min-w-0 items-center gap-3 rounded-xl border border-black/[0.1] bg-white/65 px-4 sm:w-[300px] lg:w-[340px]">
            <Search size={18} className="shrink-0 text-[#8A847E]" strokeWidth={1.8} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={i18nAttribute("搜索书名、作者或标签")}
              className="min-w-0 flex-1 bg-transparent text-sm text-[#2A2724] outline-none placeholder:text-[#98928C]"
            />
          </label>
          <div className="inline-flex h-12 w-full self-start rounded-xl bg-black/[0.035] p-1 sm:w-auto sm:self-auto" role="group" aria-label={i18nAttribute("图书类型")}>
            {formatOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setFormatFilter(option.value)}
                aria-pressed={formatFilter === option.value}
                className={cn(
                  'min-w-0 flex-1 rounded-lg px-2 text-sm transition sm:min-w-[70px] sm:flex-none sm:px-3',
                  formatFilter === option.value ? 'bg-[#F9DED4] font-medium text-[#EF4D2F] shadow-sm' : 'text-[#706A64] hover:text-[#34312E]'
                )}
              >
                {i18nAttribute(option.label)}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            aria-label={i18nAttribute("更多筛选")}
            className={cn(
              'inline-flex h-11 w-11 items-center justify-center gap-2 rounded-xl border px-0 text-sm font-medium transition sm:w-auto sm:px-4',
              filtersOpen || advancedFilterCount > 0 ? 'border-[#F3B6A4] bg-[#FFF2ED] text-[#D7462B]' : 'border-black/[0.09] bg-white/55 text-[#69635E] hover:bg-black/[0.025]'
            )}
          >
            <span className="hidden sm:inline"><I18nText>更多筛选</I18nText></span>
            {advancedFilterCount > 0 ? <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[#EF4D2F] px-1 text-[10px] text-white">{advancedFilterCount}</span> : null}
            <Filter size={15} strokeWidth={1.8} />
          </button>
        </div>
      </div> : null}

      {view === 'list' && filtersOpen ? (
        <>
          {seriesNameFilter || facetIdFilter || statusFilter !== '全部' ? <div className="mt-3 flex flex-col gap-3 rounded-2xl border border-black/[0.055] bg-black/[0.018] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2 text-xs text-[#7B746E]">
              <span><I18nText>来自当前入口的基础条件</I18nText></span>
              {seriesNameFilter ? <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#FFF2ED] px-2.5 font-medium text-[#D7462B]"><I18nText>丛书：</I18nText><span data-i18n-skip>{seriesNameFilter}</span><button type="button" aria-label={i18nAttribute("清除丛书筛选")} onClick={() => replaceRoute((params) => params.delete('seriesName'))}><X size={13} /></button></span> : null}
              {facetIdFilter ? <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#FFF2ED] px-2.5 font-medium text-[#D7462B]">{i18nAttribute(facetKindFilter === 'SERIES' ? "系列：" : "作者：")}<span data-i18n-skip>{facetNameFilter}</span><button type="button" aria-label={i18nAttribute(facetKindFilter === 'SERIES' ? "清除系列筛选" : "清除作者筛选")} onClick={() => replaceRoute((params) => {
                params.delete('facetKind');
                params.delete('facetId');
                params.delete('facetName');
              })}><X size={13} /></button></span> : null}
              {statusFilter !== '全部' ? <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#FFF2ED] px-2.5 font-medium text-[#D7462B]"><I18nText>状态：</I18nText>{statusOptions.find((item) => item.value === statusFilter)?.label}<button type="button" aria-label={i18nAttribute("清除阅读状态筛选")} onClick={() => updateStatus('全部')}><X size={13} /></button></span> : null}
            </div>
            <button type="button" disabled={advancedFilterCount === 0} onClick={clearAdvancedFilters} className="h-9 self-start rounded-lg px-2.5 text-xs font-medium text-[#77716B] transition hover:bg-white hover:text-[#EF4D2F] disabled:cursor-not-allowed disabled:opacity-35 sm:self-auto"><I18nText>清除全部筛选</I18nText></button>
          </div> : null}
          <SmartFilterBuilder
            fields={smartFilterFields}
            rules={smartFilterRules}
            loading={filterSchemaLoading || !filterSchemaLoaded}
            actions={(
              <button type="button" onClick={() => setSmartShelfOpen(true)} className="inline-flex h-10 items-center gap-2 rounded-xl border border-black/[0.09] bg-white px-3 text-sm font-medium text-[#69635E] transition hover:bg-black/[0.025]"><BookmarkPlus size={15} /><I18nText>保存筛选</I18nText></button>
            )}
            onChange={setSmartFilterRules}
          />
        </>
      ) : null}

      {message ? <div className="mt-4 text-sm text-emerald-700">{message}</div> : null}
      {loading && books.length === 0 ? <div className="mt-8 flex min-h-[240px] items-center justify-center rounded-2xl bg-black/[0.02] text-sm text-[#817B75]" role="status" aria-live="polite"><Loader2 size={17} className="mr-2 animate-spin" /><I18nText>正在读取书库...</I18nText></div> : null}
      {error ? <div className="mt-6 rounded-2xl bg-red-50 px-6 py-5 text-sm text-red-700">{error}</div> : null}

      {!loading && !error && books.length === 0 ? (
        <div className="mt-10 flex min-h-[260px] flex-col items-start justify-center rounded-2xl bg-black/[0.025] px-8">
          <div className="text-lg font-medium text-[#3A3632]"><I18nText>没有找到图书</I18nText></div>
          <p className="mt-2 text-sm text-[#817B75]">{canManageSystem ? <I18nText>调整搜索或筛选条件，也可以上传电子书、漫画或有声书文件。</I18nText> : <I18nText>调整搜索或筛选条件，或联系管理员开通更多书库范围。</I18nText>}</p>
          {canManageSystem ? <button type="button" onClick={openUploadDialog} className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-[#EF4D2F]"><UploadCloud size={17} /><I18nText>上传读物</I18nText></button> : null}
        </div>
      ) : null}

      {!error && books.length > 0 ? (
        <>
          {view === 'grid' ? (
            <div className="mt-8">
              <BookshelfCollection
                books={books}
                testId="library-book-bookshelves"
                onOpen={(book) => router.push(`/works/${book.id}`)}
              />
              <div ref={loadMoreRef} className="flex min-h-20 items-center justify-center py-5 text-xs tabular-nums text-[#8A847E]" role="status" aria-live="polite">
                {loading && page > 1 ? <><Loader2 size={15} className="mr-2 animate-spin" /><I18nText>正在加载更多图书...</I18nText></> : i18nAttribute("已加载 {value0} / {value1} 本", { value0: books.length, value1: meta.total })}
              </div>
            </div>
          ) : (
            <div className="mt-8"><BookTable books={books.filter((book): book is ManagementWorkSummary => book.projection === 'management')} onDelete={canManageSystem ? openDeleteBook : undefined} selectable selectedIds={selectedWorkIds} onSelect={(book) => toggleSelection(book.id)} onSelectAll={togglePageSelection} onSelectionChange={setSelectedWorkIds} onContextMenu={(_book, position) => setBatchContextPosition(position)} sort={sort} sortDirection={sortDirection} onSort={updateSort} /></div>
          )}

          {view === 'list' ? <Pagination page={page} totalPages={meta.totalPages} loading={loading} pageSize={pageSize} onPage={setPage} onPageSize={(nextPageSize) => { setPage(1); setPageSize(nextPageSize); }} /> : null}
        </>
      ) : null}

      {selectedWorkIds.length > 0 ? <div className="fixed bottom-5 left-1/2 z-40 flex w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 flex-wrap items-center justify-between gap-3 rounded-2xl border border-black/[0.08] bg-[#282522] px-4 py-3 text-white shadow-2xl"><div><div className="text-sm font-semibold"><I18nText>已选择 </I18nText>{selectedWorkIds.length} <I18nText>本</I18nText></div><div className="mt-0.5 hidden text-[11px] text-white/55 sm:block"><I18nText>列表中右键可直接选择批量操作</I18nText></div></div><div className="flex gap-2"><Button variant="secondary" onClick={() => { setSelectedWorkIds([]); setBatchContextPosition(null); }}><I18nText>清空</I18nText></Button><Button onClick={() => openBatchAction(canManageSystem ? 'metadata' : 'shelves')}><I18nText>批量操作</I18nText></Button></div></div> : null}

      <LibraryBatchContextMenu position={batchContextPosition} selectedCount={selectedWorkIds.length} canManageSystem={canManageSystem} onClose={() => setBatchContextPosition(null)} onSelect={openBatchAction} />
      <LibraryBatchDialog action={batchDialogAction} selectedIds={selectedWorkIds} canManageSystem={canManageSystem} onActionChange={setBatchDialogAction} onClose={() => setBatchDialogAction(null)} onApplied={finishBatchAction} />
    </div>
  );
}

function Pagination({ page, totalPages, loading, pageSize, onPage, onPageSize }: { page: number; totalPages: number; loading: boolean; pageSize: string; onPage: (page: number) => void; onPageSize: (pageSize: string) => void }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const candidates = Array.from(new Set([1, page - 1, page, page + 1, totalPages])).filter((item) => item >= 1 && item <= totalPages).sort((a, b) => a - b);
  return (
    <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
    {totalPages > 1 ? <nav className="flex items-center justify-center gap-1.5" aria-label={i18nAttribute("书库分页")}>
      <button type="button" aria-label={i18nAttribute("上一页")} disabled={page <= 1 || loading} onClick={() => onPage(Math.max(1, page - 1))} className="flex h-9 w-9 items-center justify-center rounded-lg text-[#736D67] hover:bg-black/[0.035] disabled:opacity-30">
        <ChevronLeft size={18} />
      </button>
      {candidates.map((item, index) => {
        const previous = candidates[index - 1];
        return (
          <span key={item} className="contents">
            {previous && item - previous > 1 ? <span className="px-1 text-sm text-[#9A948E]">…</span> : null}
            <button
              type="button"
              aria-label={i18nAttribute("第 {value0} 页", { value0: item })}
              aria-current={item === page ? 'page' : undefined}
              disabled={loading}
              onClick={() => onPage(item)}
              className={cn('flex h-9 min-w-9 items-center justify-center rounded-lg px-2 text-sm transition', item === page ? 'bg-[#F9DED4] font-medium text-[#EF4D2F]' : 'text-[#625D58] hover:bg-black/[0.035]')}
            >
              {item}
            </button>
          </span>
        );
      })}
      <button type="button" aria-label={i18nAttribute("下一页")} disabled={page >= totalPages || loading} onClick={() => onPage(Math.min(totalPages, page + 1))} className="flex h-9 w-9 items-center justify-center rounded-lg text-[#736D67] hover:bg-black/[0.035] disabled:opacity-30">
        <ChevronRight size={18} />
      </button>
    </nav> : null}
    <Select value={pageSize} options={pageSizeOptions} onChange={onPageSize} ariaLabel={i18nAttribute("每页数量")} size="sm" className="min-w-[104px]" align="right" />
    </div>
  );
}
