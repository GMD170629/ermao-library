'use client';

import { ArrowLeft, BookOpen, Check, Edit3, Loader2, Plus, Save, Search, Trash2, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import { BookshelfCollection, type BookshelfItem } from '../../components/book/bookshelf';
import { Cover } from '../../components/book/cover';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useConfirm, useToast } from '../../components/ui/feedback';
import { PageTitle } from '../../components/ui/page-title';
import { summarizeSmartShelfRules, type SmartShelfRules } from './smart-shelf-rules';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type BookSearchItem = BookshelfItem & { format: string };

type ShelfView = {
  id: string;
  name: string;
  description: string | null;
  bookCount: number;
  bookIds?: string[];
  books?: BookshelfItem[];
  page?: number;
  pageSize?: number;
  total?: number;
  totalPages?: number;
  createdAt: string;
  updatedAt: string;
  kind?: 'STATIC' | 'SMART';
  rules?: SmartShelfRules;
  pinned?: boolean;
};

type ShelvesPayload = {
  ok: boolean;
  data?: { shelves: ShelfView[] };
  error?: { message: string };
};

type ShelfPayload = {
  ok: boolean;
  data?: { shelf: ShelfView };
  error?: { message: string };
};

type BooksPayload = {
  ok: boolean;
  data?: { books: BookSearchItem[] };
  error?: { message: string };
};

const emptyForm = { name: '', description: '' };

async function readPayload<T extends { ok: boolean; error?: { message: string } }>(response: Response, fallback: string): Promise<T> {
  const payload = (await response.json().catch(() => null)) as T | null;
  if (!response.ok || !payload?.ok) throw new Error(payload?.error?.message ?? fallback);
  return payload;
}

export function ShelvesPage() {
  const { t: i18nAttribute } = useAttributeI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const currentSearch = searchParams.toString();
  const [shelves, setShelves] = useState<ShelfView[]>([]);
  const [activeShelf, setActiveShelf] = useState<ShelfView | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [selectedBookIds, setSelectedBookIds] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [searchBooks, setSearchBooks] = useState<BookSearchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const openRequestRef = useRef(0);
  const loadMoreRef = useRef<HTMLDivElement>(null);
  const confirm = useConfirm();
  const toast = useToast();

  const route = useMemo(() => new URLSearchParams(currentSearch), [currentSearch]);
  const activeIsNew = activeId === 'new';
  const editing = activeIsNew || (Boolean(activeId) && route.get('edit') === '1' && Boolean(activeShelf));
  const activeIsSmart = activeShelf?.kind === 'SMART';
  const smartRuleSummaries = useMemo(() => summarizeSmartShelfRules(activeShelf?.rules), [activeShelf?.rules]);

  useEffect(() => {
    void loadShelves();
  }, []);

  useEffect(() => {
    const requestedShelf = route.get('shelf');
    if (route.get('create') === '1') {
      openRequestRef.current += 1;
      openCreate();
    } else if (requestedShelf) {
      void openShelf(requestedShelf);
    } else {
      openRequestRef.current += 1;
      setActiveId(null);
      setActiveShelf(null);
      setSelectedBookIds([]);
      setSearch('');
      setSearchBooks([]);
      setForm(emptyForm);
      setError('');
    }
  }, [route]);

  useEffect(() => {
    if (!editing || activeIsSmart || !activeId || search.trim().length === 0) {
      setSearchBooks([]);
      setSearchLoading(false);
      return;
    }
    let active = true;
    const params = new URLSearchParams({ pageSize: '16', visibility: 'active', sort: 'title', view: 'search', search: search.trim() });
    setSearchLoading(true);
    fetch(`/api/works?${params}`)
      .then((response) => readPayload<BooksPayload>(response, '搜索图书失败'))
      .then((payload) => {
        if (active) setSearchBooks(payload.data?.books ?? []);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : '搜索图书失败');
      })
      .finally(() => {
        if (active) setSearchLoading(false);
      });
    return () => {
      active = false;
    };
  }, [activeId, activeIsSmart, editing, search]);

  useEffect(() => {
    const sentinel = loadMoreRef.current;
    const currentPage = activeShelf?.page ?? 1;
    const totalPages = activeShelf?.totalPages ?? 1;
    if (!sentinel || detailLoading || loadingMore || !activeShelf || currentPage >= totalPages) return;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      void openShelf(activeShelf.id, currentPage + 1, true);
    }, { rootMargin: '700px 0px' });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [activeShelf, detailLoading, loadingMore]);

  const previewBooksById = useMemo(() => {
    const books = new Map<string, BookshelfItem>();
    [...(activeShelf?.books ?? []), ...searchBooks].forEach((book) => books.set(book.id, book));
    return books;
  }, [activeShelf, searchBooks]);
  const selectedBooks = selectedBookIds.map((id) => previewBooksById.get(id)).filter(Boolean) as BookshelfItem[];
  const shelfBooks = activeShelf?.books ?? [];
  const initialBookIds = activeShelf?.bookIds ?? (activeShelf?.books ?? []).map((book) => book.id);
  const hasUnsavedChanges = activeIsNew
    ? Boolean(form.name.trim() || form.description.trim() || selectedBookIds.length)
    : activeShelf ? (
      form.name.trim() !== activeShelf.name
      || form.description.trim() !== (activeShelf.description ?? '')
      || (!activeIsSmart && selectedBookIds.join('\u0000') !== initialBookIds.join('\u0000'))
    ) : false;

  async function loadShelves() {
    setLoading(true);
    setError('');
    try {
      const payload = await readPayload<ShelvesPayload>(await fetch('/api/shelves'), '读取书架失败');
      setShelves(payload.data?.shelves ?? []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取书架失败');
    } finally {
      setLoading(false);
    }
  }

  async function openShelf(id: string, page = 1, append = false) {
    const requestId = openRequestRef.current + 1;
    openRequestRef.current = requestId;
    setActiveId(id);
    if (append) setLoadingMore(true);
    else setDetailLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        page: String(page),
        pageSize: '24',
        includeBookIds: page === 1 ? 'true' : 'false'
      });
      const payload = await readPayload<ShelfPayload>(await fetch(`/api/shelves/${id}?${params}`), '读取书架详情失败');
      if (requestId !== openRequestRef.current || !payload.data) return;
      const shelf = payload.data.shelf;
      setActiveShelf((current) => {
        if (!append || !current || current.id !== shelf.id) return shelf;
        const books = new Map((current.books ?? []).map((book) => [book.id, book]));
        (shelf.books ?? []).forEach((book) => books.set(book.id, book));
        return {
          ...shelf,
          bookIds: shelf.bookIds ?? current.bookIds,
          books: Array.from(books.values())
        };
      });
      if (!append) {
        setForm({ name: shelf.name, description: shelf.description ?? '' });
        setSelectedBookIds(shelf.bookIds ?? (shelf.books ?? []).map((book) => book.id));
        setSearch('');
        setSearchBooks([]);
      }
    } catch (reason) {
      if (requestId === openRequestRef.current) setError(reason instanceof Error ? reason.message : '读取书架详情失败');
    } finally {
      if (requestId === openRequestRef.current) {
        setDetailLoading(false);
        setLoadingMore(false);
      }
    }
  }

  function openCreate() {
    setActiveId('new');
    setActiveShelf(null);
    setForm(emptyForm);
    setSelectedBookIds([]);
    setSearch('');
    setSearchBooks([]);
    setError('');
  }

  async function leaveEditor() {
    if (hasUnsavedChanges) {
      const discard = await confirm({
        title: '放弃未保存的更改',
        description: activeIsSmart ? '书架名称和描述的更改不会保留。' : '书架名称、描述和图书调整都不会保留。',
        confirmLabel: '放弃更改',
        tone: 'danger'
      });
      if (!discard) return;
    }
    router.push(activeIsNew || !activeShelf ? '/shelves' : `/shelves?shelf=${encodeURIComponent(activeShelf.id)}`, { scroll: false });
  }

  function toggleBook(bookId: string, checked: boolean) {
    setSelectedBookIds((current) => (checked ? [...new Set([...current, bookId])] : current.filter((id) => id !== bookId)));
  }

  async function saveShelf() {
    const name = form.name.trim();
    if (!name) {
      setError('请填写书架名称');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const response = await fetch(activeIsNew ? '/api/shelves' : `/api/shelves/${activeId}`, {
        method: activeIsNew ? 'POST' : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          description: form.description.trim(),
          ...(!activeIsSmart ? { bookIds: selectedBookIds } : {})
        })
      });
      const payload = await readPayload<ShelfPayload>(response, '保存书架失败');
      if (!payload.data) throw new Error('保存书架失败');
      const saved = payload.data.shelf;
      setActiveShelf(saved);
      setActiveId(saved.id);
      setForm({ name: saved.name, description: saved.description ?? '' });
      setSelectedBookIds(saved.bookIds ?? (saved.books ?? []).map((book) => book.id));
      await loadShelves();
      window.dispatchEvent(new Event('shuku:shelves-changed'));
      toast.success(activeIsNew ? '书架已创建' : '书架更改已保存');
      router.replace(`/shelves?shelf=${encodeURIComponent(saved.id)}`, { scroll: false });
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '保存书架失败';
      setError(nextError);
      toast.error('保存书架失败', nextError);
    } finally {
      setSaving(false);
    }
  }

  async function deleteShelf() {
    if (!activeShelf) return;
    const approved = await confirm({
      title: '删除书架',
      description: activeIsSmart
        ? `删除智能书架“${activeShelf.name}”？自动收录规则会被删除，但图书仍会保留在书库中。`
        : `删除书架“${activeShelf.name}”？书架中的图书仍会保留在书库中。`,
      confirmLabel: '删除书架',
      tone: 'danger'
    });
    if (!approved) return;
    setSaving(true);
    setError('');
    try {
      await readPayload(await fetch(`/api/shelves/${activeShelf.id}`, { method: 'DELETE' }), '删除书架失败');
      await loadShelves();
      window.dispatchEvent(new Event('shuku:shelves-changed'));
      toast.success('书架已删除');
      router.replace('/shelves', { scroll: false });
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '删除书架失败';
      setError(nextError);
      toast.error('删除书架失败', nextError);
    } finally {
      setSaving(false);
    }
  }

  const pageAction = activeId ? (
    <div className="flex flex-wrap gap-2">
      <Button variant="secondary" icon={ArrowLeft} onClick={() => editing ? void leaveEditor() : router.push('/shelves', { scroll: false })}>
        {editing ? i18nAttribute("取消") : i18nAttribute("全部书架")}
      </Button>
      {!editing && activeShelf ? <Button icon={Edit3} onClick={() => router.push(`/shelves?shelf=${encodeURIComponent(activeShelf.id)}&edit=1`, { scroll: false })}><I18nText>管理书架</I18nText></Button> : null}
      {editing ? <Button icon={Save} loading={saving} loadingText={i18nAttribute("保存中")} disabled={detailLoading} onClick={saveShelf}>{activeIsNew ? i18nAttribute("创建书架") : i18nAttribute("保存更改")}</Button> : null}
    </div>
  ) : <Button icon={Plus} onClick={() => router.push('/shelves?create=1', { scroll: false })}><I18nText>创建书架</I18nText></Button>;

  return (
    <div className="shuku-content-frame space-y-6">
      <PageTitle
        title={activeIsNew ? i18nAttribute("创建书架") : activeShelf?.name ?? (activeId ? i18nAttribute("书架详情") : i18nAttribute("书架"))}
        translateTitle={!activeShelf}
        desc={activeIsNew
          ? i18nAttribute("填写基本信息，也可以现在就加入第一批图书。")
          : activeShelf
            ? i18nAttribute("{value0} 本图书{value1}", { value0: activeShelf.bookCount, value1: activeShelf.kind === 'SMART' ? ' · 智能书架，结果自动更新' : activeShelf.description ? ` · ${activeShelf.description}` : '' })
            : i18nAttribute("创建自定义书架，按主题、系列或阅读计划整理图书。")}
        action={pageAction}
      />

      {error ? <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div> : null}

      {activeId && detailLoading ? <div className="shuku-loading-panel p-6 text-sm" role="status" aria-live="polite"><I18nText>正在读取书架详情...</I18nText></div> : null}

      {activeId && !detailLoading && editing ? (
        <section className="rounded-[24px] border border-[#E5DED8] bg-white p-5 shadow-[0_12px_36px_rgba(63,48,40,0.06)] md:p-6">
          <div className="flex flex-col gap-3 border-b border-[#EEE8E3] pb-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2 font-semibold text-[#2A2825]"><Edit3 size={17} /> {activeIsNew ? i18nAttribute("书架信息") : i18nAttribute("编辑书架")}</div>
              <div className="mt-1 text-sm text-[#7C756F]">{activeIsSmart ? i18nAttribute("可以修改基本信息并查看自动收录条件；图书由规则自动管理。") : i18nAttribute("勾选或移除图书后，点击“{value0}”统一生效。", { value0: activeIsNew ? '创建书架' : '保存更改' })}</div>
            </div>
            <Badge>{activeIsSmart ? activeShelf?.bookCount ?? 0 : selectedBookIds.length} <I18nText>本图书</I18nText></Badge>
          </div>

          <div className="mt-5 grid gap-6 xl:grid-cols-[minmax(0,1fr)_390px]">
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-[minmax(0,320px)_1fr]">
                <label className="block">
                  <span className="text-sm font-medium text-[#5F5954]"><I18nText>名称 </I18nText><span className="text-[#D94724]">*</span></span>
                  <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-[#DED8D1] px-4 text-sm outline-none transition focus:border-[#ED9D86] focus:ring-4 focus:ring-[#FFE4DC]" placeholder={i18nAttribute("例如：周末阅读、轻小说收藏")} autoFocus={activeIsNew} />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-[#5F5954]"><I18nText>描述 </I18nText><span className="font-normal text-[#9A938D]"><I18nText>选填</I18nText></span></span>
                  <input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-[#DED8D1] px-4 text-sm outline-none transition focus:border-[#ED9D86] focus:ring-4 focus:ring-[#FFE4DC]" placeholder={i18nAttribute("这个书架收录什么图书")} />
                </label>
              </div>

              {activeIsSmart ? (
                <div>
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                      <div className="text-sm font-semibold text-[#2A2825]"><I18nText>自动加入条件</I18nText></div>
                      <div className="mt-1 text-xs leading-5 text-[#8A837D]"><I18nText>基础条件需全部满足</I18nText>{activeShelf?.rules?.conditions?.length ? i18nAttribute("，组合条件{value0}", { value0: activeShelf.rules.combinator === 'ANY' ? '满足任一条即可' : '需全部满足' }) : ''}<I18nText>。图书不能手动加入或移出。</I18nText></div>
                    </div>
                    <Badge tone="amber"><I18nText>智能书架</I18nText></Badge>
                  </div>
                  {smartRuleSummaries.length > 0 ? (
                    <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                      {smartRuleSummaries.map((rule, index) => (
                        <div key={`${rule.label}-${index}`} className="rounded-2xl border border-[#E8E0D9] bg-[#FAF8F6] px-4 py-3">
                          <dt className="text-xs font-medium text-[#8D857E]">{rule.label}</dt>
                          <dd className="mt-1 text-sm font-medium text-[#403C38]">{rule.value}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <div className="mt-3 rounded-2xl border border-dashed border-[#DCD5CE] bg-[#FAF8F6] px-4 py-5 text-sm text-[#746E68]"><I18nText>没有额外筛选条件，将自动收录全部可见图书。</I18nText></div>
                  )}
                </div>
              ) : <div>
                <div className="mb-3 flex items-center justify-between">
                  <div className="text-sm font-semibold text-[#2A2825]"><I18nText>书架中的图书</I18nText></div>
                  <span className="text-xs text-[#8A837D]"><I18nText>移除只影响本书架，不会删除图书</I18nText></span>
                </div>
                {selectedBooks.length > 0 ? (
                  <>
                    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
                      {selectedBooks.map((book) => (
                        <div key={book.id} className="group rounded-[16px] bg-[#F7F4F1] p-2.5">
                          <Cover book={book} className="aspect-[2/3] w-full" size="small" />
                          <div data-i18n-skip className="mt-2 line-clamp-1 text-sm font-medium text-[#2A2825]">{book.title}</div>
                          <button type="button" onClick={() => toggleBook(book.id, false)} className="mt-2 inline-flex h-8 w-full items-center justify-center gap-1 rounded-lg bg-white text-xs font-medium text-red-600 outline-none transition hover:bg-red-50 focus-visible:ring-2 focus-visible:ring-red-200">
                            <X size={13} /> <I18nText>从书架移除</I18nText></button>
                        </div>
                      ))}
                    </div>
                    <ShelfLoadStatus
                      sentinelRef={loadMoreRef}
                      loading={loadingMore}
                      loaded={activeShelf?.books?.length ?? 0}
                      total={activeShelf?.total ?? activeShelf?.bookCount ?? 0}
                    />
                  </>
                ) : (
                  <div className="rounded-2xl border border-dashed border-[#DCD5CE] bg-[#FAF8F6] p-8 text-center">
                    <BookOpen size={22} className="mx-auto text-[#B3AAA2]" />
                    <div className="mt-3 text-sm font-medium text-[#5F5954]"><I18nText>书架还是空的</I18nText></div>
                    <div className="mt-1 text-sm text-[#918A84]"><I18nText>在右侧搜索图书并勾选加入。</I18nText></div>
                  </div>
                )}
              </div>}
            </div>

            {!activeIsSmart ? <aside className="self-start rounded-[20px] bg-[#F6F3F0] p-4 xl:sticky xl:top-6">
              <div className="text-sm font-semibold text-[#2A2825]"><I18nText>添加图书</I18nText></div>
              <div className="mt-1 text-xs leading-5 text-[#827B75]"><I18nText>按书名、作者或标签搜索，勾选后随书架一起保存。</I18nText></div>
              <div className="mt-3 flex h-11 items-center gap-2 rounded-xl border border-[#DED8D1] bg-white px-3 transition focus-within:border-[#ED9D86] focus-within:ring-4 focus-within:ring-[#FFE4DC]">
                <Search size={16} className="text-[#AAA29B]" />
                <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={i18nAttribute("搜索书名、作者或标签")} className="w-full bg-transparent text-sm outline-none" />
              </div>
              <div className="mt-4 max-h-[520px] space-y-2 overflow-y-auto pr-1">
                {!search.trim() ? <div className="rounded-xl bg-white/70 p-4 text-sm text-[#8D857E]"><I18nText>输入关键词开始查找。</I18nText></div> : null}
                {searchLoading ? <div className="rounded-xl bg-white/70 p-4 text-sm text-[#8D857E]"><I18nText>正在搜索...</I18nText></div> : null}
                {!searchLoading && search.trim() && searchBooks.length === 0 ? <div className="rounded-xl bg-white/70 p-4 text-sm text-[#8D857E]"><I18nText>没有找到匹配的图书。</I18nText></div> : null}
                {!searchLoading && searchBooks.map((book) => {
                  const checked = selectedBookIds.includes(book.id);
                  return (
                    <label key={book.id} className={cn('flex cursor-pointer items-center gap-3 rounded-xl border bg-white p-2.5 transition', checked ? 'border-[#F0AA96] ring-2 ring-[#FBE1D9]' : 'border-transparent hover:border-[#E3DAD3]')}>
                      <input type="checkbox" checked={checked} onChange={(event) => toggleBook(book.id, event.target.checked)} className="h-4 w-4 accent-[#E94B27]" />
                      <Cover book={book} className="h-16 w-11 shrink-0" small />
                      <div data-i18n-skip className="min-w-0 flex-1">
                        <div className="line-clamp-1 text-sm font-medium text-[#2A2825]">{book.title}</div>
                        <div className="mt-1 line-clamp-1 text-xs text-[#8B847E]">{book.author || i18nAttribute("未知作者")} · {book.format}</div>
                      </div>
                      {checked ? <Check size={16} className="shrink-0 text-[#D94724]" /> : null}
                    </label>
                  );
                })}
              </div>
            </aside> : (
              <aside className="self-start rounded-[20px] border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900 xl:sticky xl:top-6">
                <div className="font-semibold"><I18nText>图书自动管理</I18nText></div>
                <div className="mt-1"><I18nText>智能书架会随图书信息和阅读状态变化自动更新，因此不提供手动添加或移除。</I18nText></div>
              </aside>
            )}
          </div>

          {!activeIsNew ? (
            <div className="mt-6 flex flex-col gap-3 border-t border-[#EEE8E3] pt-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm text-[#817A74]">{activeIsSmart ? i18nAttribute("删除智能书架只会删除自动收录规则，不会删除任何图书。") : i18nAttribute("不再需要这个分类时，可以只删除书架，图书会继续保留在书库。")}</div>
              <Button variant="danger" icon={Trash2} disabled={saving} onClick={deleteShelf}><I18nText>删除书架</I18nText></Button>
            </div>
          ) : null}
        </section>
      ) : null}

      {activeId && !detailLoading && !editing && activeShelf ? (
        <section>
          <div className="mb-5 flex flex-col gap-3 border-b border-[#E7E0DA] pb-5 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="text-sm font-medium text-[#716A64]"><I18nText>收录图书</I18nText></div>
              <div className="mt-1 text-sm text-[#948C85]">{activeShelf.kind === 'SMART' ? i18nAttribute("符合保存条件的图书会自动加入或移出；点击封面查看详情。") : i18nAttribute("点击封面查看图书详情；使用“管理书架”调整名称和图书。")}</div>
            </div>
            <Badge>{activeShelf.bookCount} <I18nText>本</I18nText></Badge>
          </div>
          {shelfBooks.length > 0 ? (
            <>
              <BookshelfCollection
                books={shelfBooks}
                testId="shelf-book-bookshelves"
                onOpen={(book) => router.push(`/works/${book.id}`)}
              />
              <ShelfLoadStatus
                sentinelRef={loadMoreRef}
                loading={loadingMore}
                loaded={shelfBooks.length}
                total={activeShelf.total ?? activeShelf.bookCount}
              />
            </>
          ) : (
            <div className="rounded-[24px] border border-dashed border-[#DCD5CE] bg-[#FAF8F6] px-6 py-12 text-center">
              <BookOpen size={28} className="mx-auto text-[#B4ABA4]" />
              <div className="mt-4 font-semibold text-[#403C38]"><I18nText>这个书架还没有图书</I18nText></div>
              <div className="mt-1 text-sm text-[#8D857E]">{activeShelf.kind === 'SMART' ? i18nAttribute("当前没有图书符合保存的筛选条件。") : i18nAttribute("打开管理页，搜索并加入想放在这里的图书。")}</div>
              {activeShelf.kind !== 'SMART' ? <Button className="mt-5" icon={Plus} onClick={() => router.push(`/shelves?shelf=${encodeURIComponent(activeShelf.id)}&edit=1`, { scroll: false })}><I18nText>添加图书</I18nText></Button> : null}
            </div>
          )}
        </section>
      ) : null}

      {!activeId && loading ? <div className="shuku-loading-panel p-6 text-sm" role="status" aria-live="polite"><I18nText>正在读取书架...</I18nText></div> : null}
      {!activeId && !loading && shelves.length === 0 ? (
        <div className="rounded-[24px] border border-dashed border-[#DCD5CE] bg-[#FAF8F6] px-6 py-12 text-center">
          <BookOpen size={28} className="mx-auto text-[#B4ABA4]" />
          <div className="mt-4 font-semibold text-[#403C38]"><I18nText>还没有自定义书架</I18nText></div>
          <div className="mt-1 text-sm text-[#8D857E]"><I18nText>按主题、阅读计划或收藏方式创建第一个书架。</I18nText></div>
          <Button className="mt-5" icon={Plus} onClick={() => router.push('/shelves?create=1', { scroll: false })}><I18nText>创建第一个书架</I18nText></Button>
        </div>
      ) : null}
      {!activeId && !loading && shelves.length > 0 ? (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {shelves.map((shelf) => (
            <button
              key={shelf.id}
              type="button"
              onClick={() => router.push(`/shelves?shelf=${encodeURIComponent(shelf.id)}`, { scroll: false })}
              className="group rounded-[22px] border border-[#E5DED8] bg-white p-4 text-left outline-none transition duration-200 hover:-translate-y-0.5 hover:border-[#E9B7A7] hover:shadow-[0_12px_28px_rgba(73,52,43,0.09)] focus-visible:ring-4 focus-visible:ring-[#FBE1D9]"
            >
              <div className="flex h-32 items-end overflow-hidden rounded-[16px] bg-[#F4F0EC] px-5 pb-3">
                {(shelf.books ?? []).slice(0, 3).map((book, index) => (
                  <Cover key={`${book.id}-${index}`} book={book} className={cn('h-24 w-16 shrink-0 shadow-md transition duration-200 group-hover:-translate-y-1', index > 0 && '-ml-3')} small />
                ))}
                {(shelf.books ?? []).length === 0 ? <div className="flex w-full items-center justify-center self-center text-sm text-[#A09790]"><BookOpen size={17} className="mr-2" /> <I18nText>暂无图书</I18nText></div> : null}
              </div>
              <div className="mt-4">
                <div className="flex items-center gap-2"><div data-i18n-skip className="line-clamp-1 font-semibold text-[#2A2825]">{shelf.name}</div>{shelf.kind === 'SMART' ? <Badge tone="amber"><I18nText>智能</I18nText></Badge> : null}</div>
                <div data-i18n-skip={shelf.description ? '' : undefined} className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 text-[#817A74]">{shelf.description || i18nAttribute("自定义书架")}</div>
                <div className="mt-3 flex items-center justify-between border-t border-[#EEE8E3] pt-3 text-xs text-[#938B84]">
                  <span>{shelf.bookCount} <I18nText>本图书</I18nText></span>
                  <span className="font-medium text-[#D94724] transition group-hover:translate-x-0.5"><I18nText>打开书架 →</I18nText></span>
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ShelfLoadStatus({
  sentinelRef,
  loading,
  loaded,
  total
}: {
  sentinelRef: { current: HTMLDivElement | null };
  loading: boolean;
  loaded: number;
  total: number;
}) {
  const { t: i18nAttribute } = useAttributeI18n();

  return (
    <div ref={sentinelRef} className="flex min-h-20 items-center justify-center py-5 text-xs tabular-nums text-[#8A847E]" role="status" aria-live="polite">
      {loading
        ? <><Loader2 size={15} className="mr-2 animate-spin" /><I18nText>正在加载更多图书...</I18nText></>
        : i18nAttribute("已加载 {value0} / {value1} 本", { value0: loaded, value1: total })}
    </div>
  );
}
