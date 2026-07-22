'use client';

import { ArrowLeft, BookOpen, Check, Edit3, Plus, Save, Search, Trash2, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import { BookCard } from '../../components/book/book-card';
import { Cover } from '../../components/book/cover';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useConfirm, useToast } from '../../components/ui/feedback';
import { PageTitle } from '../../components/ui/page-title';
import type { WorkView } from '../../types/work';

type ShelfView = {
  id: string;
  name: string;
  description: string | null;
  bookCount: number;
  bookIds?: string[];
  books?: WorkView[];
  createdAt: string;
  updatedAt: string;
  kind?: 'STATIC' | 'SMART';
  rules?: {
    search?: string;
    statuses?: string[];
    mediaKinds?: string[];
    tags?: string[];
    combinator?: 'ALL' | 'ANY';
    conditions?: Array<{ field: string; operator: string; value?: string | string[] }>;
  };
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
  data?: { books: WorkView[] };
  error?: { message: string };
};

const emptyForm = { name: '', description: '' };

async function readPayload<T extends { ok: boolean; error?: { message: string } }>(response: Response, fallback: string): Promise<T> {
  const payload = (await response.json().catch(() => null)) as T | null;
  if (!response.ok || !payload?.ok) throw new Error(payload?.error?.message ?? fallback);
  return payload;
}

export function ShelvesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const currentSearch = searchParams.toString();
  const [shelves, setShelves] = useState<ShelfView[]>([]);
  const [activeShelf, setActiveShelf] = useState<ShelfView | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [selectedBookIds, setSelectedBookIds] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [searchBooks, setSearchBooks] = useState<WorkView[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const openRequestRef = useRef(0);
  const confirm = useConfirm();
  const toast = useToast();

  const route = useMemo(() => new URLSearchParams(currentSearch), [currentSearch]);
  const activeIsNew = activeId === 'new';
  const editing = activeIsNew || (Boolean(activeId) && route.get('edit') === '1' && activeShelf?.kind !== 'SMART');

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
    if (!editing || !activeId || search.trim().length === 0) {
      setSearchBooks([]);
      setSearchLoading(false);
      return;
    }
    let active = true;
    const params = new URLSearchParams({ pageSize: '16', visibility: 'active', sort: 'title', search: search.trim() });
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
  }, [activeId, editing, search]);

  const previewBooksById = useMemo(() => {
    const books = new Map<string, WorkView>();
    [...(activeShelf?.books ?? []), ...searchBooks].forEach((book) => books.set(book.id, book));
    return books;
  }, [activeShelf, searchBooks]);
  const selectedBooks = selectedBookIds.map((id) => previewBooksById.get(id)).filter(Boolean) as WorkView[];
  const initialBookIds = activeShelf?.bookIds ?? (activeShelf?.books ?? []).map((book) => book.id);
  const hasUnsavedChanges = activeIsNew
    ? Boolean(form.name.trim() || form.description.trim() || selectedBookIds.length)
    : activeShelf ? (
      form.name.trim() !== activeShelf.name
      || form.description.trim() !== (activeShelf.description ?? '')
      || selectedBookIds.join('\u0000') !== initialBookIds.join('\u0000')
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

  async function openShelf(id: string) {
    const requestId = openRequestRef.current + 1;
    openRequestRef.current = requestId;
    setActiveId(id);
    setDetailLoading(true);
    setError('');
    try {
      const payload = await readPayload<ShelfPayload>(await fetch(`/api/shelves/${id}`), '读取书架详情失败');
      if (requestId !== openRequestRef.current || !payload.data) return;
      const shelf = payload.data.shelf;
      setActiveShelf(shelf);
      setForm({ name: shelf.name, description: shelf.description ?? '' });
      setSelectedBookIds(shelf.bookIds ?? (shelf.books ?? []).map((book) => book.id));
      setSearch('');
      setSearchBooks([]);
    } catch (reason) {
      if (requestId === openRequestRef.current) setError(reason instanceof Error ? reason.message : '读取书架详情失败');
    } finally {
      if (requestId === openRequestRef.current) setDetailLoading(false);
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
        description: '书架名称、描述和图书调整都不会保留。',
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
        body: JSON.stringify({ name, description: form.description.trim(), bookIds: selectedBookIds })
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
      description: `删除书架“${activeShelf.name}”？书架中的图书仍会保留在书库中。`,
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
        {editing ? '取消' : '全部书架'}
      </Button>
      {!editing && activeShelf?.kind !== 'SMART' && activeShelf ? <Button icon={Edit3} onClick={() => router.push(`/shelves?shelf=${encodeURIComponent(activeShelf.id)}&edit=1`, { scroll: false })}>管理书架</Button> : null}
      {editing ? <Button icon={Save} loading={saving} loadingText="保存中" disabled={detailLoading} onClick={saveShelf}>{activeIsNew ? '创建书架' : '保存更改'}</Button> : null}
    </div>
  ) : <Button icon={Plus} onClick={() => router.push('/shelves?create=1', { scroll: false })}>创建书架</Button>;

  return (
    <div className="shuku-content-frame space-y-6">
      <PageTitle
        title={activeIsNew ? '创建书架' : activeShelf?.name ?? (activeId ? '书架详情' : '书架')}
        desc={activeIsNew
          ? '填写基本信息，也可以现在就加入第一批图书。'
          : activeShelf
            ? `${activeShelf.bookCount} 本图书${activeShelf.kind === 'SMART' ? ' · 智能书架，结果自动更新' : activeShelf.description ? ` · ${activeShelf.description}` : ''}`
            : '创建自定义书架，按主题、系列或阅读计划整理图书。'}
        action={pageAction}
      />

      {error ? <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div> : null}

      {activeId && detailLoading ? <div className="shuku-loading-panel p-6 text-sm" role="status" aria-live="polite">正在读取书架详情...</div> : null}

      {activeId && !detailLoading && editing ? (
        <section className="rounded-[24px] border border-[#E5DED8] bg-white p-5 shadow-[0_12px_36px_rgba(63,48,40,0.06)] md:p-6">
          <div className="flex flex-col gap-3 border-b border-[#EEE8E3] pb-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2 font-semibold text-[#2A2825]"><Edit3 size={17} /> {activeIsNew ? '书架信息' : '编辑书架'}</div>
              <div className="mt-1 text-sm text-[#7C756F]">勾选或移除图书后，点击“{activeIsNew ? '创建书架' : '保存更改'}”统一生效。</div>
            </div>
            <Badge>{selectedBookIds.length} 本图书</Badge>
          </div>

          <div className="mt-5 grid gap-6 xl:grid-cols-[minmax(0,1fr)_390px]">
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-[minmax(0,320px)_1fr]">
                <label className="block">
                  <span className="text-sm font-medium text-[#5F5954]">名称 <span className="text-[#D94724]">*</span></span>
                  <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-[#DED8D1] px-4 text-sm outline-none transition focus:border-[#ED9D86] focus:ring-4 focus:ring-[#FFE4DC]" placeholder="例如：周末阅读、轻小说收藏" autoFocus={activeIsNew} />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-[#5F5954]">描述 <span className="font-normal text-[#9A938D]">选填</span></span>
                  <input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} className="mt-2 h-11 w-full rounded-xl border border-[#DED8D1] px-4 text-sm outline-none transition focus:border-[#ED9D86] focus:ring-4 focus:ring-[#FFE4DC]" placeholder="这个书架收录什么图书" />
                </label>
              </div>

              <div>
                <div className="mb-3 flex items-center justify-between">
                  <div className="text-sm font-semibold text-[#2A2825]">书架中的图书</div>
                  <span className="text-xs text-[#8A837D]">移除只影响本书架，不会删除图书</span>
                </div>
                {selectedBooks.length > 0 ? (
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
                    {selectedBooks.map((book) => (
                      <div key={book.id} className="group rounded-[16px] bg-[#F7F4F1] p-2.5">
                        <Cover book={book} className="aspect-[2/3] w-full" size="small" />
                        <div className="mt-2 line-clamp-1 text-sm font-medium text-[#2A2825]">{book.title}</div>
                        <button type="button" onClick={() => toggleBook(book.id, false)} className="mt-2 inline-flex h-8 w-full items-center justify-center gap-1 rounded-lg bg-white text-xs font-medium text-red-600 outline-none transition hover:bg-red-50 focus-visible:ring-2 focus-visible:ring-red-200">
                          <X size={13} /> 从书架移除
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-[#DCD5CE] bg-[#FAF8F6] p-8 text-center">
                    <BookOpen size={22} className="mx-auto text-[#B3AAA2]" />
                    <div className="mt-3 text-sm font-medium text-[#5F5954]">书架还是空的</div>
                    <div className="mt-1 text-sm text-[#918A84]">在右侧搜索图书并勾选加入。</div>
                  </div>
                )}
              </div>
            </div>

            <aside className="self-start rounded-[20px] bg-[#F6F3F0] p-4 xl:sticky xl:top-6">
              <div className="text-sm font-semibold text-[#2A2825]">添加图书</div>
              <div className="mt-1 text-xs leading-5 text-[#827B75]">按书名、作者或标签搜索，勾选后随书架一起保存。</div>
              <div className="mt-3 flex h-11 items-center gap-2 rounded-xl border border-[#DED8D1] bg-white px-3 transition focus-within:border-[#ED9D86] focus-within:ring-4 focus-within:ring-[#FFE4DC]">
                <Search size={16} className="text-[#AAA29B]" />
                <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索书名、作者或标签" className="w-full bg-transparent text-sm outline-none" />
              </div>
              <div className="mt-4 max-h-[520px] space-y-2 overflow-y-auto pr-1">
                {!search.trim() ? <div className="rounded-xl bg-white/70 p-4 text-sm text-[#8D857E]">输入关键词开始查找。</div> : null}
                {searchLoading ? <div className="rounded-xl bg-white/70 p-4 text-sm text-[#8D857E]">正在搜索...</div> : null}
                {!searchLoading && search.trim() && searchBooks.length === 0 ? <div className="rounded-xl bg-white/70 p-4 text-sm text-[#8D857E]">没有找到匹配的图书。</div> : null}
                {!searchLoading && searchBooks.map((book) => {
                  const checked = selectedBookIds.includes(book.id);
                  return (
                    <label key={book.id} className={cn('flex cursor-pointer items-center gap-3 rounded-xl border bg-white p-2.5 transition', checked ? 'border-[#F0AA96] ring-2 ring-[#FBE1D9]' : 'border-transparent hover:border-[#E3DAD3]')}>
                      <input type="checkbox" checked={checked} onChange={(event) => toggleBook(book.id, event.target.checked)} className="h-4 w-4 accent-[#E94B27]" />
                      <Cover book={book} className="h-16 w-11 shrink-0" small />
                      <div className="min-w-0 flex-1">
                        <div className="line-clamp-1 text-sm font-medium text-[#2A2825]">{book.title}</div>
                        <div className="mt-1 line-clamp-1 text-xs text-[#8B847E]">{book.author || '未知作者'} · {book.format}</div>
                      </div>
                      {checked ? <Check size={16} className="shrink-0 text-[#D94724]" /> : null}
                    </label>
                  );
                })}
              </div>
            </aside>
          </div>

          {!activeIsNew ? (
            <div className="mt-6 flex flex-col gap-3 border-t border-[#EEE8E3] pt-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm text-[#817A74]">不再需要这个分类时，可以只删除书架，图书会继续保留在书库。</div>
              <Button variant="danger" icon={Trash2} disabled={saving} onClick={deleteShelf}>删除书架</Button>
            </div>
          ) : null}
        </section>
      ) : null}

      {activeId && !detailLoading && !editing && activeShelf ? (
        <section>
          <div className="mb-5 flex flex-col gap-3 border-b border-[#E7E0DA] pb-5 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="text-sm font-medium text-[#716A64]">收录图书</div>
              <div className="mt-1 text-sm text-[#948C85]">{activeShelf.kind === 'SMART' ? '符合保存条件的图书会自动加入或移出；点击封面查看详情。' : '点击封面查看图书详情；使用“管理书架”调整名称和图书。'}</div>
            </div>
            <Badge>{activeShelf.bookCount} 本</Badge>
          </div>
          {(activeShelf.books ?? []).length > 0 ? (
            <div
              data-testid="shelf-book-grid"
              className="grid grid-cols-2 gap-7 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5"
            >
              {(activeShelf.books ?? []).map((book) => <BookCard key={book.id} book={book} onClick={() => router.push(`/works/${book.id}`)} />)}
            </div>
          ) : (
            <div className="rounded-[24px] border border-dashed border-[#DCD5CE] bg-[#FAF8F6] px-6 py-12 text-center">
              <BookOpen size={28} className="mx-auto text-[#B4ABA4]" />
              <div className="mt-4 font-semibold text-[#403C38]">这个书架还没有图书</div>
              <div className="mt-1 text-sm text-[#8D857E]">{activeShelf.kind === 'SMART' ? '当前没有图书符合保存的筛选条件。' : '打开管理页，搜索并加入想放在这里的图书。'}</div>
              {activeShelf.kind !== 'SMART' ? <Button className="mt-5" icon={Plus} onClick={() => router.push(`/shelves?shelf=${encodeURIComponent(activeShelf.id)}&edit=1`, { scroll: false })}>添加图书</Button> : null}
            </div>
          )}
        </section>
      ) : null}

      {!activeId && loading ? <div className="shuku-loading-panel p-6 text-sm" role="status" aria-live="polite">正在读取书架...</div> : null}
      {!activeId && !loading && shelves.length === 0 ? (
        <div className="rounded-[24px] border border-dashed border-[#DCD5CE] bg-[#FAF8F6] px-6 py-12 text-center">
          <BookOpen size={28} className="mx-auto text-[#B4ABA4]" />
          <div className="mt-4 font-semibold text-[#403C38]">还没有自定义书架</div>
          <div className="mt-1 text-sm text-[#8D857E]">按主题、阅读计划或收藏方式创建第一个书架。</div>
          <Button className="mt-5" icon={Plus} onClick={() => router.push('/shelves?create=1', { scroll: false })}>创建第一个书架</Button>
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
                {(shelf.books ?? []).length === 0 ? <div className="flex w-full items-center justify-center self-center text-sm text-[#A09790]"><BookOpen size={17} className="mr-2" /> 暂无图书</div> : null}
              </div>
              <div className="mt-4">
                <div className="flex items-center gap-2"><div className="line-clamp-1 font-semibold text-[#2A2825]">{shelf.name}</div>{shelf.kind === 'SMART' ? <Badge tone="amber">智能</Badge> : null}</div>
                <div className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 text-[#817A74]">{shelf.description || '自定义书架'}</div>
                <div className="mt-3 flex items-center justify-between border-t border-[#EEE8E3] pt-3 text-xs text-[#938B84]">
                  <span>{shelf.bookCount} 本图书</span>
                  <span className="font-medium text-[#D94724] transition group-hover:translate-x-0.5">打开书架 →</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
