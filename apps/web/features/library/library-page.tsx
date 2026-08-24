'use client';

import { BookOpen, ChevronLeft, ChevronRight, Filter, List, Loader2, Plus, Search, UploadCloud, X } from 'lucide-react';
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
  fetchLibraryBooksPage,
  type BookshelfBookSummary,
  type LibraryBookSummary,
  type ManagementBookSummary
} from './api/books';
import { fetchLibraryFilterSchema } from './api/filtering';
import { LibraryBatchContextMenu, LibraryBatchDialog, type LibraryBatchAction } from './library-batch-actions';
import { canUseLibraryBatchAction } from './model/library-batch-action';
import {
  LibraryQueryDebouncer,
  libraryQueryDraftIsSettled,
  type LibraryQueryDraft
} from './model/library-query-debounce';
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
import { bookDetailHrefFromLibrary } from './model/library-navigation';

const statusOptions = [
  { value: '全部', label: '全部' },
  { value: 'READING', label: '在读' },
  { value: 'UNREAD', label: '未读' },
  { value: 'FINISHED', label: '已读' }
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
  const routeFilterParam = searchParams.get('filters');
  const seriesNameFilter = searchParams.get('seriesName')?.trim() ?? '';
  const rawFacetKind = searchParams.get('facetKind')?.trim().toUpperCase() ?? '';
  const facetKindFilter = rawFacetKind === 'SERIES' || rawFacetKind === 'AUTHOR'
    ? rawFacetKind
    : '';
  const facetIdFilter = facetKindFilter ? searchParams.get('facetId')?.trim() ?? '' : '';
  const facetNameFilter = facetIdFilter ? searchParams.get('facetName')?.trim() ?? '' : '';
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [statusFilter, setStatusFilter] = useState(() => routeStatus(searchParams.get('status')));
  const initialRouteSort = librarySortPreferenceFromRoute(searchParams.get('sort'), searchParams.get('sortDirection'));
  const initialSortPreference = initialRouteSort ?? DEFAULT_LIBRARY_SORT_PREFERENCE;
  const [sort, setSort] = useState<LibrarySort>(initialSortPreference.sort);
  const [sortDirection, setSortDirection] = useState<LibrarySortDirection>(initialSortPreference.direction);
  const [sortPreferenceLoaded, setSortPreferenceLoaded] = useState(initialRouteSort !== null);
  const [search, setSearch] = useState(() => searchParams.get('search') ?? '');
  const [smartFilterRules, setSmartFilterRules] = useState<SmartFilterRules>(() => parseSmartFilterRules(routeFilterParam));
  const [smartFilterFields, setSmartFilterFields] = useState<SmartFilterField[]>([]);
  const [filterSchemaLoading, setFilterSchemaLoading] = useState(false);
  const [filterSchemaLoaded, setFilterSchemaLoaded] = useState(false);
  const [books, setBooks] = useState<LibraryBookSummary[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(String(DEFAULT_LIBRARY_PAGE_SIZE));
  const [meta, setMeta] = useState({ total: 0, pageSize: DEFAULT_LIBRARY_PAGE_SIZE, totalPages: 1 });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const [pollKey, setPollKey] = useState(0);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [canManageSystem, setCanManageSystem] = useState(false);
  const [authorizationLoaded, setAuthorizationLoaded] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selectedBookIds, setSelectedBookIds] = useState<string[]>([]);
  const [batchDialogAction, setBatchDialogAction] = useState<LibraryBatchAction | null>(null);
  const [batchContextPosition, setBatchContextPosition] = useState<{ x: number; y: number } | null>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);
  const requestedScopeRef = useRef('');
  const requestedReloadKeyRef = useRef(reloadKey);
  const requestedPollKeyRef = useRef(pollKey);
  const rememberedSortPreferenceRef = useRef(initialSortPreference);
  const toast = useToast();
  const applicableRules = useMemo(
    () => applicableSmartFilterRules(smartFilterRules),
    [smartFilterRules]
  );
  const smartFilterQuery = useMemo(() => applicableRules.conditions.length > 0 ? JSON.stringify(serializableSmartFilterRules(applicableRules)) : '', [applicableRules]);
  const queryDraft = useMemo<LibraryQueryDraft>(() => ({
    search: search.trim(),
    smartFilterQuery
  }), [search, smartFilterQuery]);
  const [settledQuery, setSettledQuery] = useState<LibraryQueryDraft>(queryDraft);
  const queryDraftSettled = libraryQueryDraftIsSettled(queryDraft, settledQuery);
  const pendingResourceCount = books.reduce(
    (count, book) => count + book.resourceImportSummary.pending,
    0
  );
  const selectedLibraryCondition = smartFilterRules.conditions.find((condition) => (
    condition.field === 'library'
    && condition.operator === 'equals'
    && typeof condition.value === 'string'
    && condition.value.trim() !== ''
  ));
  const selectedLibraryName = selectedLibraryCondition
    ? searchParams.get('libraryName')?.trim() ?? ''
    : '';
  const isSeriesFacet = facetKindFilter === 'SERIES' && Boolean(facetIdFilter);
  const isAuthorFacet = facetKindFilter === 'AUTHOR' && Boolean(facetIdFilter);
  const queryBase = useMemo(() => {
    const params = new URLSearchParams();
    if (settledQuery.search) params.set('search', settledQuery.search);
    if (statusFilter !== '全部') params.set('status', statusFilter);
    if (seriesNameFilter) params.set('seriesName', seriesNameFilter);
    if (facetKindFilter && facetIdFilter) {
      params.set('facetKind', facetKindFilter);
      params.set('facetId', facetIdFilter);
    }
    if (settledQuery.smartFilterQuery) params.set('filters', settledQuery.smartFilterQuery);
    params.set('visibility', 'active');
    params.set('sort', isSeriesFacet ? 'series_index' : isAuthorFacet ? 'updated' : sort);
    params.set('sortDirection', isSeriesFacet ? 'asc' : isAuthorFacet ? 'desc' : sortDirection);
    return params.toString();
  }, [facetIdFilter, facetKindFilter, isAuthorFacet, isSeriesFacet, seriesNameFilter, settledQuery.search, settledQuery.smartFilterQuery, sort, sortDirection, statusFilter]);
  const requestPageSize = view === 'grid'
    ? String(BROWSE_LIBRARY_PAGE_SIZE)
    : pageSize === 'all'
    ? '0'
    : pageSize;
  const requestScope = `${queryBase}&pageSize=${requestPageSize}&view=${view}`;
  const bookDetailHref = (bookId: string) => bookDetailHrefFromLibrary(bookId, searchParamString);

  useEffect(() => {
    const debouncer = new LibraryQueryDebouncer(setSettledQuery);
    debouncer.update(queryDraft);
    return () => debouncer.dispose();
  }, [queryDraft]);

  useEffect(() => {
    setSmartFilterRules(parseSmartFilterRules(routeFilterParam));
  }, [routeFilterParam]);

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
    const controller = new AbortController();
    setFilterSchemaLoading(true);
    fetchLibraryFilterSchema(controller.signal)
      .then((schema) => {
        if (controller.signal.aborted) return;
        setSmartFilterFields(schema.fields);
        setFilterSchemaLoaded(true);
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        toast.error('读取筛选维度失败', reason instanceof Error ? reason.message : '请稍后重试');
      })
      .finally(() => {
        if (!controller.signal.aborted) setFilterSchemaLoading(false);
      });
    return () => controller.abort();
  }, [filterSchemaLoaded, filtersOpen, toast]);

  useEffect(() => {
    if (!sortPreferenceLoaded || !queryDraftSettled) return;
    let active = true;
    const scopeChanged = requestedScopeRef.current !== requestScope;
    const reloadChanged = requestedReloadKeyRef.current !== reloadKey;
    const pollChanged = requestedPollKeyRef.current !== pollKey;
    const requestedPage = scopeChanged || reloadChanged ? 1 : page;
    requestedScopeRef.current = requestScope;
    requestedReloadKeyRef.current = reloadKey;
    requestedPollKeyRef.current = pollKey;
    if (requestedPage !== page) setPage(requestedPage);

    const controller = new AbortController();
    if (!pollChanged) setLoading(true);
    fetchLibraryBooksPage(
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
      .finally(() => {
        if (active && !pollChanged) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [page, pollKey, queryBase, queryDraftSettled, reloadKey, requestPageSize, requestScope, sortPreferenceLoaded, view]);

  useEffect(() => {
    if (pendingResourceCount === 0) return;
    const refreshPendingBooks = () => {
      if (document.visibilityState === 'visible') setPollKey((current) => current + 1);
    };
    const intervalId = window.setInterval(refreshPendingBooks, 2_000);
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') refreshPendingBooks();
    };
    document.addEventListener('visibilitychange', refreshWhenVisible);
    window.addEventListener('focus', refreshPendingBooks);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
      window.removeEventListener('focus', refreshPendingBooks);
    };
  }, [pendingResourceCount]);

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
    setSelectedBookIds((current) => current.filter((id) => visibleIds.has(id)));
  }, [books]);

  const advancedFilterCount = [seriesNameFilter, facetIdFilter].filter(Boolean).length + smartFilterRules.conditions.length;
  const pageTitle = selectedLibraryName
    ? selectedLibraryName
    : facetNameFilter
    ? facetNameFilter
    : seriesNameFilter
    ? seriesNameFilter
    : statusFilter === 'UNREAD'
    ? '未读'
    : statusFilter === 'READING'
      ? '在读'
      : statusFilter === 'FINISHED'
        ? '已读'
        : '全部图书';

  function updateView(nextView: 'grid' | 'list') {
    setBooks([]);
    setPage(1);
    setLoading(true);
    setView(nextView);
    if (nextView === 'grid') {
      setFiltersOpen(false);
      setSelectedBookIds([]);
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

  function clearAdvancedFilters() {
    setSmartFilterRules({ combinator: 'ALL', conditions: [] });
    replaceRoute((params) => {
      params.delete('seriesName');
      params.delete('facetKind');
      params.delete('facetId');
      params.delete('facetName');
      params.delete('filters');
      params.delete('libraryName');
    });
  }

  function toggleSelection(bookId: string) {
    setSelectedBookIds((current) => current.includes(bookId) ? current.filter((id) => id !== bookId) : [...current, bookId]);
  }

  function togglePageSelection(selected: boolean) {
    setSelectedBookIds(selected ? books.map((book) => book.id) : []);
  }

  function openBatchAction(action: LibraryBatchAction) {
    if (!canUseLibraryBatchAction(action, canManageSystem)) return;
    setBatchContextPosition(null);
    setBatchDialogAction(action);
  }

  function finishBatchAction(nextMessage: string) {
    setMessage(nextMessage);
    setBatchDialogAction(null);
    setSelectedBookIds([]);
    setReloadKey((key) => key + 1);
  }

  function openBookAction(book: ManagementBookSummary, action: LibraryBatchAction) {
    if (!canUseLibraryBatchAction(action, canManageSystem)) return;
    setSelectedBookIds([book.id]);
    setBatchContextPosition(null);
    setBatchDialogAction(action);
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

      {view === 'list' ? <div className="mt-8 flex min-w-0 items-center gap-2">
        <label className="flex h-12 min-w-0 flex-1 items-center gap-3 rounded-xl border border-black/[0.1] bg-white/65 px-4">
          <Search size={18} className="shrink-0 text-[#8A847E]" strokeWidth={1.8} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={i18nAttribute("搜索书名、作者或标签")}
            className="min-w-0 flex-1 bg-transparent text-sm text-[#2A2724] outline-none placeholder:text-[#98928C]"
          />
        </label>

        <div className="flex min-w-0 items-center gap-2">
          <Select
            value={statusFilter}
            options={statusOptions}
            onChange={updateStatus}
            ariaLabel={i18nAttribute("阅读状态")}
            className="w-28 !min-w-0 shrink-0 sm:hidden"
            triggerClassName="!h-12 !rounded-xl !border-black/[0.09] !bg-white/65 !px-4 !text-sm"
          />
          <div className="hidden h-12 self-start rounded-xl bg-black/[0.035] p-1 sm:inline-flex sm:w-auto sm:self-auto" role="group" aria-label={i18nAttribute("阅读状态")}>
            {statusOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => updateStatus(option.value)}
                aria-pressed={statusFilter === option.value}
                className={cn(
                  'min-w-0 flex-1 rounded-lg px-2 text-sm transition sm:min-w-[70px] sm:flex-none sm:px-3',
                  statusFilter === option.value ? 'bg-[#F9DED4] font-medium text-[#EF4D2F] shadow-sm' : 'text-[#706A64] hover:text-[#34312E]'
                )}
              >
                {i18nAttribute(option.label)}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            aria-label={i18nAttribute("更多筛选")}
            className={cn(
              'relative inline-flex h-12 w-12 items-center justify-center gap-2 overflow-visible rounded-xl border px-0 text-sm font-medium transition sm:w-auto sm:px-4',
              filtersOpen || advancedFilterCount > 0 ? 'border-[#F3B6A4] bg-[#FFF2ED] text-[#D7462B]' : 'border-black/[0.09] bg-white/55 text-[#69635E] hover:bg-black/[0.025]'
            )}
          >
            <span className="hidden sm:inline"><I18nText>更多筛选</I18nText></span>
            {advancedFilterCount > 0 ? <span data-testid="library-advanced-filter-count" className="absolute -right-1.5 -top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-[#EF4D2F] px-1 text-[10px] leading-none text-white shadow-[0_0_0_2px_#FFFEFC] sm:static sm:shadow-none">{advancedFilterCount}</span> : null}
            <Filter size={15} strokeWidth={1.8} />
          </button>
        </div>
      </div> : null}

      {view === 'list' && filtersOpen ? (
        <>
          {seriesNameFilter || facetIdFilter ? <div className="mt-3 flex flex-col gap-3 rounded-2xl border border-black/[0.055] bg-black/[0.018] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2 text-xs text-[#7B746E]">
              <span><I18nText>来自当前入口的基础条件</I18nText></span>
              {seriesNameFilter ? <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#FFF2ED] px-2.5 font-medium text-[#D7462B]"><I18nText>丛书：</I18nText><span data-i18n-skip>{seriesNameFilter}</span><button type="button" aria-label={i18nAttribute("清除丛书筛选")} onClick={() => replaceRoute((params) => params.delete('seriesName'))}><X size={13} /></button></span> : null}
              {facetIdFilter ? <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#FFF2ED] px-2.5 font-medium text-[#D7462B]">{i18nAttribute(facetKindFilter === 'SERIES' ? "系列：" : "作者：")}<span data-i18n-skip>{facetNameFilter}</span><button type="button" aria-label={i18nAttribute(facetKindFilter === 'SERIES' ? "清除系列筛选" : "清除作者筛选")} onClick={() => replaceRoute((params) => {
                params.delete('facetKind');
                params.delete('facetId');
                params.delete('facetName');
              })}><X size={13} /></button></span> : null}
            </div>
            <button type="button" disabled={advancedFilterCount === 0} onClick={clearAdvancedFilters} className="h-9 self-start rounded-lg px-2.5 text-xs font-medium text-[#77716B] transition hover:bg-white hover:text-[#EF4D2F] disabled:cursor-not-allowed disabled:opacity-35 sm:self-auto"><I18nText>清除全部筛选</I18nText></button>
          </div> : null}
          <SmartFilterBuilder
            fields={smartFilterFields}
            rules={smartFilterRules}
            loading={filterSchemaLoading || !filterSchemaLoaded}
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
          <p className="mt-2 text-sm text-[#817B75]">{canManageSystem ? <I18nText>调整搜索或筛选条件，也可以上传支持的图书文件格式。</I18nText> : <I18nText>调整搜索或筛选条件，或联系管理员开通更多书库范围。</I18nText>}</p>
          {canManageSystem ? <button type="button" onClick={openUploadDialog} className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-[#EF4D2F]"><UploadCloud size={17} /><I18nText>上传读物</I18nText></button> : null}
        </div>
      ) : null}

      {!error && books.length > 0 ? (
        <>
          {view === 'grid' ? (
            <div className="mt-8">
              <BookshelfCollection
                books={books.filter((book): book is BookshelfBookSummary => book.projection === 'bookshelf')}
                testId="library-book-bookshelves"
                onOpen={(book) => router.push(bookDetailHref(book.id))}
              />
              <div ref={loadMoreRef} className="flex min-h-20 items-center justify-center py-5 text-xs tabular-nums text-[#8A847E]" role="status" aria-live="polite">
                {loading && page > 1 ? <><Loader2 size={15} className="mr-2 animate-spin" /><I18nText>正在加载更多图书...</I18nText></> : i18nAttribute("已加载 {value0} / {value1} 本", { value0: books.length, value1: meta.total })}
              </div>
            </div>
          ) : (
            <div data-testid="library-management-viewport" className={cn('mt-8 lg:flex lg:min-h-[26rem] lg:flex-col', !filtersOpen && 'lg:h-[calc(100dvh-15.75rem)] lg:overflow-hidden')}>
              <div className="lg:min-h-0 lg:flex-1">
                <BookTable
                  books={books.filter((book): book is ManagementBookSummary => book.projection === 'management')}
                  onOpen={(book) => router.push(bookDetailHref(book.id))}
                  selectable
                  selectedIds={selectedBookIds}
                  onSelect={(book) => toggleSelection(book.id)}
                  onSelectAll={togglePageSelection}
                  onSelectionChange={setSelectedBookIds}
                  onContextMenu={(_book, position) => setBatchContextPosition(position)}
                  onEdit={canManageSystem ? (book) => openBookAction(book, 'metadata') : undefined}
                  onDelete={canManageSystem ? (book) => openBookAction(book, 'delete') : undefined}
                  sort={sort}
                  sortDirection={sortDirection}
                  onSort={updateSort}
                />
              </div>
              <Pagination page={page} total={meta.total} totalPages={meta.totalPages} loading={loading} pageSize={pageSize} onPage={setPage} onPageSize={(nextPageSize) => { setPage(1); setPageSize(nextPageSize); }} />
            </div>
          )}
        </>
      ) : null}

      {selectedBookIds.length > 0 ? <div className="fixed bottom-5 left-1/2 z-40 flex w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 flex-wrap items-center justify-between gap-3 rounded-2xl border border-black/[0.08] bg-[#282522] px-4 py-3 text-white shadow-2xl"><div><div className="text-sm font-semibold"><I18nText>已选择 </I18nText>{selectedBookIds.length} <I18nText>本</I18nText></div><div className="mt-0.5 hidden text-[11px] text-white/55 sm:block"><I18nText>列表中右键可直接选择批量操作</I18nText></div></div><div className="flex gap-2"><Button variant="secondary" onClick={() => { setSelectedBookIds([]); setBatchContextPosition(null); }}><I18nText>清空</I18nText></Button><Button onClick={() => openBatchAction(canManageSystem ? 'metadata' : 'shelves')}><I18nText>批量操作</I18nText></Button></div></div> : null}

      <LibraryBatchContextMenu position={batchContextPosition} selectedCount={selectedBookIds.length} canManageSystem={canManageSystem} onClose={() => setBatchContextPosition(null)} onSelect={openBatchAction} />
      <LibraryBatchDialog action={batchDialogAction} selectedIds={selectedBookIds} canManageSystem={canManageSystem} onActionChange={setBatchDialogAction} onClose={() => setBatchDialogAction(null)} onApplied={finishBatchAction} />
    </div>
  );
}

function paginationItems(page: number, totalPages: number): Array<number | 'ellipsis'> {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1);
  if (page <= 3) return [1, 2, 3, 4, 'ellipsis', totalPages];
  if (page >= totalPages - 2) return [1, 'ellipsis', totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
  return [1, 'ellipsis', page - 1, page, page + 1, 'ellipsis', totalPages];
}

function Pagination({ page, total, totalPages, loading, pageSize, onPage, onPageSize }: { page: number; total: number; totalPages: number; loading: boolean; pageSize: string; onPage: (page: number) => void; onPageSize: (pageSize: string) => void }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const items = paginationItems(page, Math.max(1, totalPages));
  const pageButtonClass = 'flex h-10 min-w-10 items-center justify-center rounded-xl border px-2 text-sm tabular-nums outline-none transition duration-200 focus-visible:ring-2 focus-visible:ring-[#EFAE9B] focus-visible:ring-offset-2 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-35';
  return (
    <section data-testid="library-pagination" className="mt-8 rounded-2xl border border-black/[0.07] bg-white/65 px-3 py-3 shadow-[0_8px_24px_rgba(67,50,42,0.035)] sm:px-4 lg:mt-3 lg:shrink-0" aria-label={i18nAttribute("书库分页")}>
      <div className="flex flex-col gap-3 lg:grid lg:grid-cols-[minmax(150px,1fr)_auto_minmax(150px,1fr)] lg:items-center">
        <div className="flex items-center justify-between gap-3 lg:block">
          <div className="min-w-0">
            <div className="text-sm font-semibold tabular-nums text-[#3B3632]">{i18nAttribute("共 {value0} 本图书", { value0: total })}</div>
            <div className="mt-0.5 text-xs tabular-nums text-[#8A837D]" aria-live="polite">{i18nAttribute("第 {value0} / {value1} 页", { value0: page, value1: Math.max(1, totalPages) })}</div>
          </div>
          <Select value={pageSize} options={pageSizeOptions} onChange={onPageSize} ariaLabel={i18nAttribute("每页数量")} size="sm" className="min-w-[108px] lg:hidden" triggerClassName="!h-10 !rounded-xl" align="right" />
        </div>

        <nav className="flex min-w-0 items-center justify-center gap-1" aria-label={i18nAttribute("书库分页")}>
          <button type="button" aria-label={i18nAttribute("上一页")} disabled={page <= 1 || loading} onClick={() => onPage(Math.max(1, page - 1))} className={cn(pageButtonClass, 'w-10 gap-1.5 border-transparent text-[#6F6862] hover:border-black/[0.07] hover:bg-white sm:w-auto sm:px-3')}>
            <ChevronLeft size={17} strokeWidth={1.9} />
            <span className="hidden sm:inline"><I18nText>上一页</I18nText></span>
          </button>
          {items.map((item, index) => item === 'ellipsis' ? (
            <span key={`ellipsis-${index}`} className="flex h-10 min-w-5 items-center justify-center text-sm text-[#A29A93]" aria-hidden="true">…</span>
          ) : (
            <button
              key={item}
              type="button"
              aria-label={i18nAttribute("第 {value0} 页", { value0: item })}
              aria-current={item === page ? 'page' : undefined}
              disabled={loading}
              onClick={() => onPage(item)}
              className={cn(pageButtonClass, item === page ? 'border-[#F2B7A6] bg-[#FFF0EA] font-semibold text-[#D9472B] shadow-[inset_0_0_0_1px_rgba(239,77,47,0.04)]' : 'border-transparent text-[#625D58] hover:border-black/[0.07] hover:bg-white')}
            >
              {item}
            </button>
          ))}
          <button type="button" aria-label={i18nAttribute("下一页")} disabled={page >= totalPages || loading} onClick={() => onPage(Math.min(totalPages, page + 1))} className={cn(pageButtonClass, 'w-10 gap-1.5 border-transparent text-[#6F6862] hover:border-black/[0.07] hover:bg-white sm:w-auto sm:px-3')}>
            <span className="hidden sm:inline"><I18nText>下一页</I18nText></span>
            <ChevronRight size={17} strokeWidth={1.9} />
          </button>
        </nav>

        <div className="hidden justify-self-end lg:block">
          <Select value={pageSize} options={pageSizeOptions} onChange={onPageSize} ariaLabel={i18nAttribute("每页数量")} size="sm" className="min-w-[108px]" triggerClassName="!h-10 !rounded-xl" align="right" />
        </div>
      </div>
    </section>
  );
}
