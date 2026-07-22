'use client';

import { ArrowRight, BookmarkPlus, ChevronLeft, ChevronRight, FileText, Filter, Grid3X3, List, Loader2, Plus, Search, Trash2, UploadCloud, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { BookCard } from '../../components/book/book-card';
import { BookTable } from '../../components/book/book-table';
import { TargetDirectoryPicker } from '../../components/directory/target-directory-picker';
import { MobileNavigationTrigger } from '../../components/layout/mobile-navigation';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useToast } from '../../components/ui/feedback';
import { Select } from '../../components/ui/select';
import type { WorkView } from '../../types/work';
import { LibraryBatchContextMenu, LibraryBatchDialog, type LibraryBatchAction } from './library-batch-actions';
import { SmartFilterBuilder, type SmartFilterField, type SmartFilterRules } from './smart-filter-builder';

type BooksResponse = {
  ok: boolean;
  data?: { books: WorkView[]; total: number; page: number; pageSize: number; totalPages: number };
  error?: { message: string };
};

type ImportResponse = {
  ok: boolean;
  data?: {
    queued?: number;
    taskKind?: string;
    bundleKey?: string | null;
    assetCount?: number;
    processedAssetCount?: number;
    results?: Array<{ message?: string; autoImport?: boolean; importStatus?: string }>;
  };
  error?: { message: string };
};

type FilterSchemaResponse = {
  ok: boolean;
  data?: { fields: SmartFilterField[]; maxConditions: number };
  error?: { message: string };
};

const sortOptions = [
  { value: 'recent_read', label: '最近阅读' },
  { value: 'recent_import', label: '最近加入' },
  { value: 'title', label: '标题' },
  { value: 'author', label: '作者' },
  { value: 'progress', label: '阅读进度' }
];

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
  { value: '100', label: '100 本/页' }
];

const validStatuses = new Set(statusOptions.map((option) => option.value));
const validSorts = new Set(sortOptions.map((option) => option.value));
const convertibleTextExtensions = new Set(['mobi', 'azw', 'azw3', 'prc', 'fb2', 'txt']);
const audioExtensions = new Set(['m4b', 'm4a', 'mp3']);
const DEFAULT_LIBRARY_PAGE_SIZE = 20;

function fileExtension(file: File | null) {
  return file?.name.split('.').pop()?.toLowerCase() ?? '';
}

function fileFormat(file: File | null) {
  const extension = fileExtension(file);
  return extension ? extension.toUpperCase() : '未知格式';
}

function formatFileSize(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(size < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function routeStatus(value: string | null) {
  if (value === 'WANT') return 'UNREAD';
  return value && validStatuses.has(value) ? value : '全部';
}

function routeSort(value: string | null) {
  return value && validSorts.has(value) ? value : 'recent_read';
}

function parseSmartFilterRules(value: string | null): SmartFilterRules {
  if (!value) return { combinator: 'ALL', conditions: [] };
  try {
    const parsed = JSON.parse(value) as { combinator?: string; conditions?: Array<{ field?: string; operator?: string; value?: string | string[] }> };
    const conditions = Array.isArray(parsed.conditions)
      ? parsed.conditions
          .filter((condition) => condition && typeof condition.field === 'string' && typeof condition.operator === 'string')
          .slice(0, 30)
          .map((condition, index) => ({ id: `route-filter-${index}`, field: condition.field as string, operator: condition.operator as string, value: condition.value }))
      : [];
    return { combinator: parsed.combinator === 'ANY' ? 'ANY' : 'ALL', conditions };
  } catch {
    return { combinator: 'ALL', conditions: [] };
  }
}

function serializableSmartFilterRules(rules: SmartFilterRules) {
  return {
    combinator: rules.combinator,
    conditions: rules.conditions.map(({ field, operator, value }) => ({ field, operator, ...(value === undefined ? {} : { value }) }))
  };
}

function smartFilterConditionComplete(condition: SmartFilterRules['conditions'][number]) {
  if (['is_empty', 'is_not_empty', 'is_true', 'is_false'].includes(condition.operator)) return true;
  if (condition.operator === 'between') return Array.isArray(condition.value) && condition.value.length === 2 && condition.value.every((item) => String(item).trim());
  return !Array.isArray(condition.value) && Boolean(String(condition.value ?? '').trim());
}

export function LibraryPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchParamString = searchParams.toString();
  const seriesNameFilter = searchParams.get('seriesName')?.trim() ?? '';
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [formatFilter, setFormatFilter] = useState('全部');
  const [statusFilter, setStatusFilter] = useState(() => routeStatus(searchParams.get('status')));
  const [sort, setSort] = useState(() => routeSort(searchParams.get('sort')));
  const [search, setSearch] = useState(() => searchParams.get('search') ?? '');
  const [smartFilterRules, setSmartFilterRules] = useState<SmartFilterRules>(() => parseSmartFilterRules(searchParams.get('filters')));
  const [smartFilterFields, setSmartFilterFields] = useState<SmartFilterField[]>([]);
  const [filterSchemaLoading, setFilterSchemaLoading] = useState(false);
  const [filterSchemaLoaded, setFilterSchemaLoaded] = useState(false);
  const [books, setBooks] = useState<WorkView[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(String(DEFAULT_LIBRARY_PAGE_SIZE));
  const [meta, setMeta] = useState({ total: 0, pageSize: DEFAULT_LIBRARY_PAGE_SIZE, totalPages: 1 });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(searchParams.get('upload') === '1');
  const [uploadTargetPath, setUploadTargetPath] = useState('');
  const [selectedUploadFiles, setSelectedUploadFiles] = useState<File[]>([]);
  const [uploadBookTitle, setUploadBookTitle] = useState('');
  const [uploadBookAuthor, setUploadBookAuthor] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<WorkView | null>(null);
  const [deleteSource, setDeleteSource] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [selectedWorkIds, setSelectedWorkIds] = useState<string[]>([]);
  const [batchDialogAction, setBatchDialogAction] = useState<LibraryBatchAction | null>(null);
  const [batchContextPosition, setBatchContextPosition] = useState<{ x: number; y: number } | null>(null);
  const [smartShelfOpen, setSmartShelfOpen] = useState(false);
  const [smartShelfName, setSmartShelfName] = useState('');
  const [smartShelfSaving, setSmartShelfSaving] = useState(false);
  const toast = useToast();
  const selectedUploadFile = selectedUploadFiles[0] ?? null;
  const selectedUploadSize = selectedUploadFiles.reduce((total, file) => total + file.size, 0);
  const selectedUploadIsAudio = selectedUploadFiles.length > 0
    && selectedUploadFiles.every((file) => audioExtensions.has(fileExtension(file)));
  const selectedAudioBundle = selectedUploadIsAudio && selectedUploadFiles.length > 1;
  const applicableSmartFilterRules = useMemo<SmartFilterRules>(() => ({
    combinator: smartFilterRules.combinator,
    conditions: smartFilterRules.conditions.filter(smartFilterConditionComplete)
  }), [smartFilterRules]);
  const incompleteSmartFilterCount = smartFilterRules.conditions.length - applicableSmartFilterRules.conditions.length;
  const smartFilterQuery = useMemo(() => applicableSmartFilterRules.conditions.length > 0 ? JSON.stringify(serializableSmartFilterRules(applicableSmartFilterRules)) : '', [applicableSmartFilterRules]);
  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (search.trim()) params.set('search', search.trim());
    if (formatFilter !== '全部') params.set('type', formatFilter);
    if (statusFilter !== '全部') params.set('status', statusFilter);
    if (seriesNameFilter) params.set('seriesName', seriesNameFilter);
    if (smartFilterQuery) params.set('filters', smartFilterQuery);
    params.set('visibility', 'active');
    params.set('sort', sort);
    params.set('page', String(page));
    params.set('pageSize', pageSize);
    return params.toString();
  }, [formatFilter, page, pageSize, search, seriesNameFilter, smartFilterQuery, sort, statusFilter]);

  useEffect(() => {
    setPage(1);
  }, [formatFilter, search, seriesNameFilter, smartFilterQuery, sort, statusFilter]);

  useEffect(() => {
    const savedView = window.localStorage.getItem('shuku.library.view');
    if (savedView === 'grid' || savedView === 'list') setView(savedView);
  }, []);

  useEffect(() => {
    const routeParams = new URLSearchParams(searchParamString);
    setStatusFilter(routeStatus(routeParams.get('status')));
    setSort(routeSort(routeParams.get('sort')));
    setSearch(routeParams.get('search') ?? '');
    if (routeParams.get('upload') === '1') setUploadDialogOpen(true);
  }, [searchParamString]);

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
    let active = true;
    setLoading(true);
    fetch(`/api/works?${query}`)
      .then((response) => response.json() as Promise<BooksResponse>)
      .then((payload) => {
        if (!active) return;
        if (!payload.ok) throw new Error(payload.error?.message ?? '读取书库失败');
        const data = payload.data;
        if (data && page > data.totalPages && data.totalPages > 0) {
          setPage(data.totalPages);
          return;
        }
        setBooks(data?.books ?? []);
        setMeta({
          total: data?.total ?? 0,
          pageSize: data?.pageSize ?? Number(pageSize),
          totalPages: data?.totalPages ?? 1
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
    };
  }, [page, query, reloadKey]);

  useEffect(() => {
    const visibleIds = new Set(books.map((book) => book.id));
    setSelectedWorkIds((current) => current.filter((id) => visibleIds.has(id)));
  }, [books]);

  const advancedFilterCount = [statusFilter !== '全部', seriesNameFilter].filter(Boolean).length + smartFilterRules.conditions.length;
  const pageTitle = seriesNameFilter
    ? seriesNameFilter
    : statusFilter === 'UNREAD'
    ? '未开始'
    : statusFilter === 'READING'
      ? '进行中'
      : statusFilter === 'FINISHED'
        ? '已完成'
        : '全部图书';

  function updateView(nextView: 'grid' | 'list') {
    setView(nextView);
    window.localStorage.setItem('shuku.library.view', nextView);
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

  function updateSort(nextSort: string) {
    setSort(nextSort);
    replaceRoute((params) => {
      if (nextSort === 'recent_read') params.delete('sort');
      else params.set('sort', nextSort);
    });
  }

  function openUploadDialog() {
    setSelectedUploadFiles([]);
    setUploadBookTitle('');
    setUploadBookAuthor('');
    setUploadDialogOpen(true);
  }

  function clearUploadRoute() {
    if (searchParams.get('upload') !== '1') return;
    replaceRoute((params) => params.delete('upload'));
  }

  function closeUploadDialog() {
    if (uploading) return;
    setSelectedUploadFiles([]);
    setUploadBookTitle('');
    setUploadBookAuthor('');
    setUploadDialogOpen(false);
    clearUploadRoute();
  }

  async function uploadBook() {
    const files = selectedUploadFiles;
    const file = files[0];
    if (!file || !uploadTargetPath) return;
    setUploading(true);
    setError('');
    setMessage('');
    try {
      const form = new FormData();
      form.append('targetPath', uploadTargetPath);
      if (uploadBookTitle.trim()) form.append('bookTitle', uploadBookTitle.trim());
      if (uploadBookAuthor.trim()) form.append('bookAuthor', uploadBookAuthor.trim());
      files.forEach((selectedFile) => form.append('files', selectedFile));
      const response = await fetch('/api/works/import', { method: 'POST', body: form });
      const text = await response.text();
      const payload = text ? JSON.parse(text) as ImportResponse : { ok: false, error: { message: response.ok ? '导入失败' : `上传失败（HTTP ${response.status}）` } };
      if (!payload.ok) throw new Error(payload.error?.message ?? '导入失败');
      const sourceFormat = fileFormat(file);
      const successMessage = files.length > 1
        ? `${payload.data?.assetCount ?? files.length} 个音频文件已作为一本有声书加入导入队列`
        : convertibleTextExtensions.has(fileExtension(file))
        ? `${sourceFormat} 文件已加入自动转换队列`
        : (payload.data?.results?.[0]?.message ?? `${file.name} 已加入导入队列`);
      setMessage(successMessage);
      toast.success(successMessage);
      setReloadKey((key) => key + 1);
      setSelectedUploadFiles([]);
      setUploadBookTitle('');
      setUploadBookAuthor('');
      setUploadDialogOpen(false);
      clearUploadRoute();
    } catch (reason) {
      const nextError = reason instanceof SyntaxError ? '上传失败：服务器返回了无法解析的响应，请检查反向代理上传体积限制。' : reason instanceof Error ? reason.message : '导入失败';
      setError(nextError);
      toast.error('导入失败', nextError);
    } finally {
      setUploading(false);
    }
  }

  function openDeleteBook(book: WorkView) {
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
      if (applicableSmartFilterRules.conditions.length > 0) Object.assign(rules, serializableSmartFilterRules(applicableSmartFilterRules));
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
    <div className="mx-auto max-w-[1280px]">
      <header className="flex items-start justify-between gap-6">
        <div className="flex min-w-0 items-center gap-3 sm:gap-4">
          <MobileNavigationTrigger />
          <div className="flex min-w-0 items-baseline gap-3 sm:gap-4">
            <h1 className="truncate text-[30px] font-semibold leading-none tracking-[-0.035em] text-[#1E1D1B] sm:text-[44px]">{pageTitle}</h1>
            {!loading ? <span className="shrink-0 text-[13px] text-[#8A847E] sm:text-[15px]">{meta.total} 本</span> : null}
          </div>
        </div>
        <button
          type="button"
          onClick={openUploadDialog}
          aria-label="上传读物"
          title="上传读物"
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-black/[0.12] bg-white/55 text-[#252321] transition hover:border-[#EF4D2F]/40 hover:bg-[#FFF4EF] hover:text-[#EF4D2F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
        >
          <Plus size={25} strokeWidth={1.6} />
        </button>
      </header>

      {uploadDialogOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#241F1C]/30 p-4 backdrop-blur-[2px]">
          <div className="w-full max-w-xl rounded-3xl border border-black/[0.08] bg-[#FFFEFC] p-6 shadow-[0_28px_80px_rgba(47,37,31,0.22)]">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-xl font-semibold text-[#25221F]">导入图书</div>
                <div className="mt-1.5 text-sm text-[#817B75]">可一次选择多段 MP3、M4A 或 M4B，按文件顺序合并为一本有声书。</div>
              </div>
              <button type="button" onClick={closeUploadDialog} className="inline-flex h-10 w-10 items-center justify-center rounded-full text-[#77716B] transition hover:bg-black/[0.05]" aria-label="关闭上传">
                <X size={18} />
              </button>
            </div>
            <div className="mt-6 space-y-4">
              <label className="block text-sm text-slate-600">
                图书文件
                <span className={cn('mt-2 flex min-h-14 items-center gap-3 rounded-2xl border px-4 py-3 transition', uploading ? 'cursor-not-allowed border-black/[0.05] bg-black/[0.025]' : 'cursor-pointer border-black/[0.1] bg-white hover:bg-[#FBF6F2]')}>
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#FFF0EA] text-[#D9563B]"><FileText size={18} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-[#393531]">{selectedAudioBundle ? `已选择 ${selectedUploadFiles.length} 个音频文件` : selectedUploadFile?.name ?? '选择图书文件'}</span>
                    <span className="mt-0.5 block text-xs text-[#8A847E]">{selectedUploadFile ? `${selectedAudioBundle ? '有声书音轨组' : fileFormat(selectedUploadFile)} · ${formatFileSize(selectedUploadSize)}` : '电子书、漫画与 M4B、M4A、MP3 有声书'}</span>
                  </span>
                  <span className="shrink-0 text-xs font-medium text-[#D9563B]">{selectedUploadFile ? '重新选择' : '浏览'}</span>
                  <input
                    type="file"
                    multiple
                    accept=".epub,.mobi,.azw,.azw3,.prc,.fb2,.txt,.cbz,.zip,.pdf,.m4b,.m4a,.mp3,application/epub+zip,application/zip,application/pdf,text/plain,audio/mp4,audio/mpeg"
                    className="hidden"
                    disabled={uploading}
                    onChange={(event) => {
                      const files = Array.from(event.target.files ?? []);
                      if (files.length > 1 && files.some((file) => !audioExtensions.has(fileExtension(file)))) {
                        toast.error('无法组合这些文件', '批量导入仅支持 MP3、M4A 与 M4B；其他格式请逐本导入。');
                        setSelectedUploadFiles([]);
                      } else {
                        setSelectedUploadFiles(files);
                      }
                      event.target.value = '';
                    }}
                  />
                </span>
              </label>
              {selectedUploadFiles.length === 1 && selectedUploadFile && convertibleTextExtensions.has(fileExtension(selectedUploadFile)) ? (
                <div className="rounded-2xl border border-[#F1DED6] bg-[#FFF9F6] px-4 py-3">
                  <div className="text-xs font-medium uppercase tracking-[0.12em] text-[#A56B5A]">处理方式</div>
                  <div className="mt-2 flex items-center gap-2 text-sm font-semibold text-[#3A3531]">
                    <span>{fileFormat(selectedUploadFile)}</span><ArrowRight size={15} className="text-[#C58C7A]" /><span>EPUB</span><span className="ml-auto rounded-full bg-[#FBE1D8] px-2.5 py-1 text-xs text-[#B44E35]">自动转换</span>
                  </div>
                  <div className="mt-2 text-xs leading-5 text-[#817B75]">系统会自动识别章节和书内资源；源文件会保留，转换失败时可在导入任务中查看原因。</div>
                </div>
              ) : null}
              {selectedUploadIsAudio ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="block text-sm text-slate-600">
                    有声书名称 <span className="text-xs text-[#9A948E]">（可选）</span>
                    <input
                      value={uploadBookTitle}
                      onChange={(event) => setUploadBookTitle(event.target.value)}
                      placeholder="留空时读取专辑标签"
                      className="mt-2 h-11 w-full rounded-2xl border border-black/[0.1] bg-white px-4 text-[#393531] outline-none transition placeholder:text-[#AAA49E] focus:border-[#E8A18D] focus:ring-2 focus:ring-[#F9DED4]"
                    />
                  </label>
                  <label className="block text-sm text-slate-600">
                    作者 <span className="text-xs text-[#9A948E]">（可选）</span>
                    <input
                      value={uploadBookAuthor}
                      onChange={(event) => setUploadBookAuthor(event.target.value)}
                      placeholder="留空时读取作者标签"
                      className="mt-2 h-11 w-full rounded-2xl border border-black/[0.1] bg-white px-4 text-[#393531] outline-none transition placeholder:text-[#AAA49E] focus:border-[#E8A18D] focus:ring-2 focus:ring-[#F9DED4]"
                    />
                  </label>
                  <p className="text-xs leading-5 text-[#817B75] sm:col-span-2">填写后会优先用于作品识别与现有电子书、漫画版本合并；留空则按音频标签和文件名自动识别。</p>
                </div>
              ) : null}
              <TargetDirectoryPicker
                value={uploadTargetPath}
                onChange={setUploadTargetPath}
                memory="upload"
                label="保存目录"
                requiredMessage="请选择保存目录"
                processingMode="queue"
              />
              <div className="flex justify-end gap-2 pt-1">
                <Button type="button" variant="secondary" onClick={closeUploadDialog}>取消</Button>
                <Button type="button" disabled={!uploadTargetPath || selectedUploadFiles.length === 0} loading={uploading} loadingText="正在加入队列" icon={UploadCloud} onClick={() => void uploadBook()}>开始导入</Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {deleteTarget ? (
        <div className="fixed inset-0 z-[90] flex items-end justify-center bg-[#241F1C]/35 p-0 backdrop-blur-[2px] md:items-center md:p-6" role="dialog" aria-modal="true" aria-label="删除图书记录">
          <div className="w-full max-w-lg rounded-t-3xl border border-black/[0.08] bg-[#FFFEFC] p-5 shadow-[0_28px_80px_rgba(47,37,31,0.22)] md:rounded-3xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-[#25221F]">删除图书记录</h2>
                <p className="mt-2 text-sm leading-6 text-[#6F6963]">删除《{deleteTarget.title}》的书库记录和系统生成文件。你可以选择是否同时删除源文件。</p>
              </div>
              <button type="button" disabled={deleting} onClick={() => setDeleteTarget(null)} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-[#77716B] hover:bg-black/[0.05] disabled:opacity-50" aria-label="关闭"><X size={18} /></button>
            </div>
            <label className={cn('mt-5 flex cursor-pointer gap-3 rounded-2xl border p-4 transition', deleteSource ? 'border-red-200 bg-red-50' : 'border-black/[0.08] bg-black/[0.02] hover:bg-black/[0.04]')}>
              <input type="checkbox" checked={deleteSource} disabled={deleting} onChange={(event) => setDeleteSource(event.target.checked)} className="mt-0.5 h-4 w-4 accent-red-600" />
              <span>
                <span className="block text-sm font-semibold text-[#302C29]">同步删除源文件</span>
                <span className="mt-1 block text-xs leading-5 text-[#77716B]">源文件将从监控或上传目录中永久删除；该操作无法恢复。</span>
              </span>
            </label>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="secondary" disabled={deleting} onClick={() => setDeleteTarget(null)}>取消</Button>
              <Button type="button" variant="danger" icon={Trash2} loading={deleting} loadingText="删除中" onClick={() => void deleteBook()}>{deleteSource ? '删除记录和源文件' : '删除记录'}</Button>
            </div>
          </div>
        </div>
      ) : null}

      {smartShelfOpen ? (
        <div className="fixed inset-0 z-[90] flex items-end justify-center bg-[#241F1C]/35 p-0 backdrop-blur-[2px] md:items-center md:p-6" role="dialog" aria-modal="true" aria-label="保存智能书架">
          <div className="w-full max-w-md rounded-t-3xl bg-[#FFFEFC] p-6 shadow-2xl md:rounded-3xl">
            <div className="flex items-start justify-between gap-4"><div><h2 className="text-lg font-semibold text-[#2D2926]">保存为智能书架</h2><p className="mt-1 text-sm leading-6 text-[#817B75]">保存当前搜索、类型、状态和标签条件，结果会随书库自动更新。</p></div><button type="button" onClick={() => setSmartShelfOpen(false)}><X size={18} /></button></div>
            <label className="mt-5 block text-sm text-[#6F6963]">书架名称<input autoFocus value={smartShelfName} onChange={(event) => setSmartShelfName(event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-black/[0.1] bg-white px-4 outline-none focus:border-[#E8A18D]" placeholder={pageTitle === '全部图书' ? '例如：近期科幻阅读' : pageTitle} /></label>
            <div className={cn('mt-4 rounded-xl px-4 py-3 text-xs leading-5', incompleteSmartFilterCount > 0 ? 'bg-amber-50 text-amber-800' : 'bg-black/[0.035] text-[#746E68]')}>{incompleteSmartFilterCount > 0 ? `还有 ${incompleteSmartFilterCount} 条条件没有填写完整，请返回补全后再保存。` : [search.trim() && `搜索“${search.trim()}”`, formatFilter !== '全部' && `类型：${formatOptions.find((item) => item.value === formatFilter)?.label}`, statusFilter !== '全部' && `状态：${statusOptions.find((item) => item.value === statusFilter)?.label}`, applicableSmartFilterRules.conditions.length > 0 && `${applicableSmartFilterRules.conditions.length} 条${applicableSmartFilterRules.combinator === 'ALL' ? '全部匹配' : '任一匹配'}规则`].filter(Boolean).join(' · ') || '当前没有额外条件，将包含全部可见图书'}</div>
            <div className="mt-6 flex justify-end gap-2"><Button variant="secondary" onClick={() => setSmartShelfOpen(false)}>取消</Button><Button icon={BookmarkPlus} loading={smartShelfSaving} disabled={!smartShelfName.trim() || incompleteSmartFilterCount > 0} onClick={() => void saveSmartShelf()}>保存书架</Button></div>
          </div>
        </div>
      ) : null}

      <div className="mt-8 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
          <label className="flex h-12 min-w-0 items-center gap-3 rounded-xl border border-black/[0.1] bg-white/65 px-4 sm:w-[300px] lg:w-[340px]">
            <Search size={18} className="shrink-0 text-[#8A847E]" strokeWidth={1.8} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索书名、作者或标签"
              className="min-w-0 flex-1 bg-transparent text-sm text-[#2A2724] outline-none placeholder:text-[#98928C]"
            />
          </label>
          <div className="inline-flex h-12 self-start rounded-xl bg-black/[0.035] p-1 sm:self-auto" role="group" aria-label="图书类型">
            {formatOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setFormatFilter(option.value)}
                aria-pressed={formatFilter === option.value}
                className={cn(
                  'min-w-[70px] rounded-lg px-3 text-sm transition',
                  formatFilter === option.value ? 'bg-[#F9DED4] font-medium text-[#EF4D2F] shadow-sm' : 'text-[#706A64] hover:text-[#34312E]'
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setSmartShelfOpen(true)} className="inline-flex h-11 items-center gap-2 rounded-xl border border-black/[0.09] bg-white/55 px-3 text-sm font-medium text-[#69635E] transition hover:bg-black/[0.025]"><BookmarkPlus size={16} />保存筛选</button>
          <Select value={sort} options={sortOptions} onChange={updateSort} ariaLabel="排序方式" className="min-w-[128px]" align="right" />
          <Select value={pageSize} options={pageSizeOptions} onChange={(nextPageSize) => { setPage(1); setPageSize(nextPageSize); }} ariaLabel="每页数量" className="min-w-[112px]" align="right" />
          <div className="inline-flex h-11 rounded-xl border border-black/[0.09] bg-white/55 p-1">
            <button
              type="button"
              title="网格"
              aria-label="网格"
              aria-pressed={view === 'grid'}
              onClick={() => updateView('grid')}
              className={cn('flex h-9 w-10 items-center justify-center rounded-lg transition', view === 'grid' ? 'bg-[#F9DED4] text-[#EF4D2F]' : 'text-[#756F69] hover:bg-black/[0.035]')}
            >
              <Grid3X3 size={17} />
            </button>
            <button
              type="button"
              title="列表"
              aria-label="列表"
              aria-pressed={view === 'list'}
              onClick={() => updateView('list')}
              className={cn('flex h-9 w-10 items-center justify-center rounded-lg transition', view === 'list' ? 'bg-[#F9DED4] text-[#EF4D2F]' : 'text-[#756F69] hover:bg-black/[0.035]')}
            >
              <List size={17} />
            </button>
          </div>
          <button
            type="button"
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            className={cn(
              'inline-flex h-11 items-center gap-2 rounded-xl border px-4 text-sm font-medium transition',
              filtersOpen || advancedFilterCount > 0 ? 'border-[#F3B6A4] bg-[#FFF2ED] text-[#D7462B]' : 'border-black/[0.09] bg-white/55 text-[#69635E] hover:bg-black/[0.025]'
            )}
          >
            更多筛选
            {advancedFilterCount > 0 ? <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[#EF4D2F] px-1 text-[10px] text-white">{advancedFilterCount}</span> : null}
            <Filter size={15} strokeWidth={1.8} />
          </button>
        </div>
      </div>

      {filtersOpen ? (
        <>
          {seriesNameFilter || statusFilter !== '全部' ? <div className="mt-3 flex flex-col gap-3 rounded-2xl border border-black/[0.055] bg-black/[0.018] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2 text-xs text-[#7B746E]">
              <span>来自当前入口的基础条件</span>
              {seriesNameFilter ? <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#FFF2ED] px-2.5 font-medium text-[#D7462B]">丛书：{seriesNameFilter}<button type="button" aria-label="清除丛书筛选" onClick={() => replaceRoute((params) => params.delete('seriesName'))}><X size={13} /></button></span> : null}
              {statusFilter !== '全部' ? <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#FFF2ED] px-2.5 font-medium text-[#D7462B]">状态：{statusOptions.find((item) => item.value === statusFilter)?.label}<button type="button" aria-label="清除阅读状态筛选" onClick={() => updateStatus('全部')}><X size={13} /></button></span> : null}
            </div>
            <button type="button" disabled={advancedFilterCount === 0} onClick={clearAdvancedFilters} className="h-9 self-start rounded-lg px-2.5 text-xs font-medium text-[#77716B] transition hover:bg-white hover:text-[#EF4D2F] disabled:cursor-not-allowed disabled:opacity-35 sm:self-auto">清除全部筛选</button>
          </div> : null}
          <SmartFilterBuilder fields={smartFilterFields} rules={smartFilterRules} loading={filterSchemaLoading || !filterSchemaLoaded} onChange={setSmartFilterRules} />
        </>
      ) : null}

      {message ? <div className="mt-4 text-sm text-emerald-700">{message}</div> : null}
      {loading ? <div className="mt-8 flex min-h-[240px] items-center justify-center rounded-2xl bg-black/[0.02] text-sm text-[#817B75]" role="status" aria-live="polite"><Loader2 size={17} className="mr-2 animate-spin" />正在读取书库...</div> : null}
      {error ? <div className="mt-6 rounded-2xl bg-red-50 px-6 py-5 text-sm text-red-700">{error}</div> : null}

      {!loading && !error && books.length === 0 ? (
        <div className="mt-10 flex min-h-[260px] flex-col items-start justify-center rounded-2xl bg-black/[0.025] px-8">
          <div className="text-lg font-medium text-[#3A3632]">没有找到图书</div>
          <p className="mt-2 text-sm text-[#817B75]">调整搜索或筛选条件，也可以上传电子书、漫画或有声书文件。</p>
          <button type="button" onClick={openUploadDialog} className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-[#EF4D2F]"><UploadCloud size={17} />上传读物</button>
        </div>
      ) : null}

      {!loading && !error && books.length > 0 ? (
        <>
          {view === 'grid' ? (
            <div
              data-testid="library-book-grid"
              className="mt-7 grid grid-cols-2 gap-7 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5"
            >
              {books.map((book, index) => (
                <BookCard
                  key={book.id}
                  book={book}
                  priority={index === 0}
                  onDelete={() => openDeleteBook(book)}
                  onClick={() => router.push(`/works/${book.id}`)}
                  selectable
                  selected={selectedWorkIds.includes(book.id)}
                  onSelect={() => toggleSelection(book.id)}
                />
              ))}
            </div>
          ) : (
            <div className="mt-8"><BookTable books={books} onDelete={openDeleteBook} selectable selectedIds={selectedWorkIds} onSelect={(book) => toggleSelection(book.id)} onSelectAll={togglePageSelection} onSelectionChange={setSelectedWorkIds} onContextMenu={(_book, position) => setBatchContextPosition(position)} /></div>
          )}

          {meta.totalPages > 1 ? <Pagination page={page} totalPages={meta.totalPages} loading={loading} onPage={setPage} /> : null}
        </>
      ) : null}

      {selectedWorkIds.length > 0 ? <div className="fixed bottom-5 left-1/2 z-40 flex w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 flex-wrap items-center justify-between gap-3 rounded-2xl border border-black/[0.08] bg-[#282522] px-4 py-3 text-white shadow-2xl"><div><div className="text-sm font-semibold">已选择 {selectedWorkIds.length} 本</div><div className="mt-0.5 hidden text-[11px] text-white/55 sm:block">列表中右键可直接选择批量操作</div></div><div className="flex gap-2"><Button variant="secondary" onClick={() => { setSelectedWorkIds([]); setBatchContextPosition(null); }}>清空</Button><Button onClick={() => openBatchAction('metadata')}>批量操作</Button></div></div> : null}

      <LibraryBatchContextMenu position={batchContextPosition} selectedCount={selectedWorkIds.length} onClose={() => setBatchContextPosition(null)} onSelect={openBatchAction} />
      <LibraryBatchDialog action={batchDialogAction} selectedIds={selectedWorkIds} onActionChange={setBatchDialogAction} onClose={() => setBatchDialogAction(null)} onApplied={finishBatchAction} />
    </div>
  );
}

function Pagination({ page, totalPages, loading, onPage }: { page: number; totalPages: number; loading: boolean; onPage: (page: number) => void }) {
  const candidates = Array.from(new Set([1, page - 1, page, page + 1, totalPages])).filter((item) => item >= 1 && item <= totalPages).sort((a, b) => a - b);
  return (
    <nav className="mt-10 flex items-center justify-center gap-1.5" aria-label="书库分页">
      <button type="button" aria-label="上一页" disabled={page <= 1 || loading} onClick={() => onPage(Math.max(1, page - 1))} className="flex h-9 w-9 items-center justify-center rounded-lg text-[#736D67] hover:bg-black/[0.035] disabled:opacity-30">
        <ChevronLeft size={18} />
      </button>
      {candidates.map((item, index) => {
        const previous = candidates[index - 1];
        return (
          <span key={item} className="contents">
            {previous && item - previous > 1 ? <span className="px-1 text-sm text-[#9A948E]">…</span> : null}
            <button
              type="button"
              aria-label={`第 ${item} 页`}
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
      <button type="button" aria-label="下一页" disabled={page >= totalPages || loading} onClick={() => onPage(Math.min(totalPages, page + 1))} className="flex h-9 w-9 items-center justify-center rounded-lg text-[#736D67] hover:bg-black/[0.035] disabled:opacity-30">
        <ChevronRight size={18} />
      </button>
    </nav>
  );
}
