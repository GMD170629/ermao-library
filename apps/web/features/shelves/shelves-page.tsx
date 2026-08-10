'use client';

import { ArrowLeft, BookOpen, Check, Edit3, Folders, Loader2, Plus, Save, Search, Sparkles, Trash2, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import { BookshelfCollection, type BookshelfItem } from '../../components/book/bookshelf';
import { Cover } from '../../components/book/cover';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useConfirm, useToast } from '../../components/ui/feedback';
import { PageTitle } from '../../components/ui/page-title';
import {
  applicableSmartFilterRules,
  fetchLibraryFilterSchema,
  mediaKindsLabel,
  serializableSmartFilterRules,
  SmartFilterBuilder,
  type SmartFilterField,
  type SmartFilterRules as LibrarySmartFilterRules
} from '../library/public';
import {
  deleteShelfById,
  fetchShelf,
  fetchShelves,
  ShelfApiError,
  writeShelf,
  type ShelfKind,
  type ShelfView
} from './public';
import { summarizeSmartShelfRules } from './smart-shelf-rules';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type BookSearchItem = BookshelfItem;

type BooksPayload = {
  ok: boolean;
  data?: {
    books: BookSearchItem[];
    total?: number;
    page?: number;
    pageSize?: number;
    totalPages?: number;
  };
  error?: { message: string };
};

const emptyForm = { name: '', description: '' };
const emptySmartFilterRules: LibrarySmartFilterRules = { combinator: 'ALL', conditions: [] };

async function readPayload<T extends { ok: boolean; error?: { message: string } }>(response: Response, fallback: string): Promise<T> {
  const payload = (await response.json().catch(() => null)) as T | null;
  if (!response.ok || !payload?.ok) throw new Error(payload?.error?.message ?? fallback);
  return payload;
}

export function ShelvesPage() {
  const { t: i18nAttribute, locale } = useAttributeI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const currentSearch = searchParams.toString();
  const [shelves, setShelves] = useState<ShelfView[]>([]);
  const [activeShelf, setActiveShelf] = useState<ShelfView | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [draftKind, setDraftKind] = useState<ShelfKind>('STATIC');
  const [selectedBookIds, setSelectedBookIds] = useState<string[]>([]);
  const [selectedMemberShelfIds, setSelectedMemberShelfIds] = useState<string[]>([]);
  const [selectedCollectionIds, setSelectedCollectionIds] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [searchBooks, setSearchBooks] = useState<BookSearchItem[]>([]);
  const [smartFilterFields, setSmartFilterFields] = useState<SmartFilterField[]>([]);
  const [smartFilterRules, setSmartFilterRules] = useState<LibrarySmartFilterRules>(emptySmartFilterRules);
  const [filterSchemaLoading, setFilterSchemaLoading] = useState(false);
  const [filterSchemaLoaded, setFilterSchemaLoaded] = useState(false);
  const [filterSchemaError, setFilterSchemaError] = useState('');
  const [previewBooks, setPreviewBooks] = useState<BookSearchItem[]>([]);
  const [previewTotal, setPreviewTotal] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
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
  const editing = activeIsNew || (
    Boolean(activeId)
    && route.get('edit') === '1'
    && Boolean(activeShelf)
  );
  const activeKind = activeIsNew ? draftKind : activeShelf?.kind ?? 'STATIC';
  const activeIsSmart = activeKind === 'SMART';
  const activeIsCollection = activeKind === 'COLLECTION';
  const smartRuleSummaries = useMemo(() => summarizeSmartShelfRules(activeShelf?.rules), [activeShelf?.rules]);
  const applicableRules = useMemo(
    () => applicableSmartFilterRules(smartFilterRules),
    [smartFilterRules]
  );
  const incompleteSmartFilterCount = smartFilterRules.conditions.length - applicableRules.conditions.length;
  const smartFilterQuery = useMemo(
    () => applicableRules.conditions.length > 0
      ? JSON.stringify(serializableSmartFilterRules(applicableRules))
      : '',
    [applicableRules]
  );

  useEffect(() => {
    void loadShelves();
  }, []);

  useEffect(() => {
    const requestedShelf = route.get('shelf');
    if (route.get('create') === '1') {
      openRequestRef.current += 1;
      openCreate(
        route.get('kind') === 'smart'
          ? 'SMART'
          : route.get('kind') === 'collection'
            ? 'COLLECTION'
            : 'STATIC'
      );
    } else if (requestedShelf) {
      void openShelf(requestedShelf);
    } else {
      openRequestRef.current += 1;
      setActiveId(null);
      setActiveShelf(null);
      setSelectedBookIds([]);
      setSelectedMemberShelfIds([]);
      setSelectedCollectionIds([]);
      setSearch('');
      setSearchBooks([]);
      setDraftKind('STATIC');
      setSmartFilterRules(emptySmartFilterRules);
      setFilterSchemaError('');
      setPreviewBooks([]);
      setPreviewTotal(0);
      setPreviewError('');
      setForm(emptyForm);
      setError('');
    }
  }, [route]);

  useEffect(() => {
    if (!editing || activeIsSmart || activeIsCollection || !activeId || search.trim().length === 0) {
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
  }, [activeId, activeIsCollection, activeIsSmart, editing, search]);

  useEffect(() => {
    if (!activeIsNew || !activeIsSmart || filterSchemaLoaded) return;
    const controller = new AbortController();
    setFilterSchemaLoading(true);
    setFilterSchemaError('');
    fetchLibraryFilterSchema(controller.signal)
      .then((schema) => {
        setSmartFilterFields(schema.fields);
        setFilterSchemaLoaded(true);
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        setFilterSchemaError(reason instanceof Error ? reason.message : i18nAttribute("读取筛选条件失败"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setFilterSchemaLoading(false);
      });
    return () => controller.abort();
  }, [activeIsNew, activeIsSmart, filterSchemaLoaded, i18nAttribute]);

  useEffect(() => {
    if (!activeIsNew || !activeIsSmart) {
      setPreviewBooks([]);
      setPreviewTotal(0);
      setPreviewLoading(false);
      setPreviewError('');
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({
        page: '1',
        pageSize: '3',
        visibility: 'active',
        sort: 'updated',
        sortDirection: 'desc',
        view: 'search'
      });
      if (smartFilterQuery) params.set('filters', smartFilterQuery);
      setPreviewLoading(true);
      setPreviewError('');
      fetch(`/api/works?${params}`, {
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal
      })
        .then((response) => readPayload<BooksPayload>(response, i18nAttribute("读取匹配预览失败")))
        .then((payload) => {
          setPreviewBooks(payload.data?.books ?? []);
          setPreviewTotal(payload.data?.total ?? payload.data?.books.length ?? 0);
        })
        .catch((reason) => {
          if (controller.signal.aborted) return;
          setPreviewError(reason instanceof Error ? reason.message : i18nAttribute("读取匹配预览失败"));
        })
        .finally(() => {
          if (!controller.signal.aborted) setPreviewLoading(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [activeIsNew, activeIsSmart, i18nAttribute, smartFilterQuery]);

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
  const memberShelves = activeShelf?.shelves ?? [];
  const initialBookIds = activeShelf?.bookIds ?? (activeShelf?.books ?? []).map((book) => book.id);
  const initialMemberShelfIds = activeShelf?.memberShelfIds ?? memberShelves.map((shelf) => shelf.id);
  const initialCollectionIds = activeShelf?.collectionIds ?? [];
  const memberShelfOptions = shelves.filter((shelf) => shelf.kind !== 'COLLECTION');
  const collectionOptions = shelves.filter(
    (shelf) => (
      shelf.kind === 'COLLECTION'
      && shelf.id !== activeShelf?.id
    )
  );
  const hasUnsavedChanges = activeIsNew
    ? Boolean(
        form.name.trim()
        || form.description.trim()
        || draftKind !== 'STATIC'
        || selectedBookIds.length
        || selectedMemberShelfIds.length
        || selectedCollectionIds.length
      )
    : activeShelf ? (
      form.name.trim() !== activeShelf.name
      || form.description.trim() !== (activeShelf.description ?? '')
      || (activeIsCollection
        ? selectedMemberShelfIds.join('\u0000') !== initialMemberShelfIds.join('\u0000')
        : selectedCollectionIds.join('\u0000') !== initialCollectionIds.join('\u0000')
          || (!activeIsSmart && selectedBookIds.join('\u0000') !== initialBookIds.join('\u0000')))
    ) : false;

  function shelfErrorMessage(reason: unknown, fallback: string): string {
    if (!(reason instanceof ShelfApiError)) {
      return reason instanceof Error ? reason.message : fallback;
    }
    switch (reason.code) {
      case 'SHELF_COLLECTION_NOT_EMPTY':
        return i18nAttribute("合集仍有书架，请先移除全部书架");
      case 'INVALID_COLLECTION_MEMBER':
        return i18nAttribute("合集只能包含自己的普通或智能书架");
      case 'COLLECTION_CANNOT_CONTAIN_WORKS':
        return i18nAttribute("合集不能包含图书");
      case 'COLLECTION_CANNOT_HAVE_RULES':
        return i18nAttribute("合集不能设置智能书架规则");
      default:
        return reason.message || fallback;
    }
  }

  async function loadShelves() {
    setLoading(true);
    setError('');
    try {
      setShelves(await fetchShelves());
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
      const shelf = await fetchShelf(id, {
        page,
        pageSize: 24,
        includeIds: page === 1
      });
      if (requestId !== openRequestRef.current) return;
      setActiveShelf((current) => {
        if (!append || !current || current.id !== shelf.id) return shelf;
        if (shelf.kind === 'COLLECTION') {
          const members = new Map((current.shelves ?? []).map((member) => [member.id, member]));
          (shelf.shelves ?? []).forEach((member) => members.set(member.id, member));
          return {
            ...shelf,
            memberShelfIds: shelf.memberShelfIds ?? current.memberShelfIds,
            shelves: Array.from(members.values())
          };
        }
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
        setDraftKind(shelf.kind ?? 'STATIC');
        setSmartFilterRules({
          combinator: shelf.rules?.combinator === 'ANY' ? 'ANY' : 'ALL',
          conditions: [
            ...(shelf.rules?.conditions ?? []).map((condition, index) => ({
              id: `shelf-rule-${index}`,
              field: condition.field,
              operator: condition.operator,
              value: condition.value
            })),
            ...(shelf.rules?.publishers ?? []).map((publisher, index) => ({
              id: `shelf-legacy-publisher-${index}`,
              field: 'publisher',
              operator: 'equals',
              value: publisher
            }))
          ]
        });
        setSelectedBookIds(shelf.bookIds ?? (shelf.books ?? []).map((book) => book.id));
        setSelectedMemberShelfIds(shelf.memberShelfIds ?? (shelf.shelves ?? []).map((member) => member.id));
        setSelectedCollectionIds(shelf.collectionIds ?? []);
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

  function openCreate(kind: ShelfKind = 'STATIC') {
    setActiveId('new');
    setActiveShelf(null);
    setForm(emptyForm);
    setDraftKind(kind);
    setSmartFilterRules(emptySmartFilterRules);
    setFilterSchemaError('');
    setSelectedBookIds([]);
    setSelectedMemberShelfIds([]);
    setSelectedCollectionIds([]);
    setSearch('');
    setSearchBooks([]);
    setPreviewBooks([]);
    setPreviewTotal(0);
    setPreviewError('');
    setError('');
  }

  async function leaveEditor() {
    if (hasUnsavedChanges) {
      const discard = await confirm({
        title: '放弃未保存的更改',
        description: activeIsCollection
          ? '合集名称、描述和成员调整都不会保留。'
          : activeIsSmart
            ? '书架名称、描述和合集归属的更改不会保留。'
            : '书架名称、描述、图书和合集归属调整都不会保留。',
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
    if (activeIsSmart && incompleteSmartFilterCount > 0) {
      setError(i18nAttribute("还有 {value0} 条条件没有填写完整，请补全后再创建。", { value0: incompleteSmartFilterCount }));
      return;
    }
    setSaving(true);
    setError('');
    try {
      const saved = await writeShelf(activeIsNew ? null : activeId, {
        name,
        description: form.description.trim(),
        ...(activeIsNew ? { kind: activeKind } : {}),
        ...(activeIsCollection
          ? { memberShelfIds: selectedMemberShelfIds }
          : {
              collectionIds: selectedCollectionIds,
              ...(activeIsSmart
                ? { rules: serializableSmartFilterRules(applicableRules), pinned: true }
                : !activeIsSmart
                  ? { bookIds: selectedBookIds }
                  : {})
            })
      });
      setActiveShelf(saved);
      setActiveId(saved.id);
      setDraftKind(saved.kind ?? 'STATIC');
      setForm({ name: saved.name, description: saved.description ?? '' });
      setSelectedBookIds(saved.bookIds ?? (saved.books ?? []).map((book) => book.id));
      setSelectedMemberShelfIds(saved.memberShelfIds ?? (saved.shelves ?? []).map((member) => member.id));
      setSelectedCollectionIds(saved.collectionIds ?? []);
      await loadShelves();
      window.dispatchEvent(new Event('shuku:shelves-changed'));
      toast.success(
        activeIsNew
          ? activeIsCollection
            ? '合集已创建'
            : '书架已创建'
          : activeIsCollection
            ? '合集更改已保存'
            : '书架更改已保存'
      );
      router.replace(`/shelves?shelf=${encodeURIComponent(saved.id)}`, { scroll: false });
    } catch (reason) {
      const nextError = shelfErrorMessage(reason, '保存书架失败');
      setError(nextError);
      toast.error('保存书架失败', nextError);
    } finally {
      setSaving(false);
    }
  }

  async function deleteShelf() {
    if (!activeShelf) return;
    if (activeIsCollection && (activeShelf.shelfCount ?? 0) > 0) {
      setError(i18nAttribute("合集仍有书架，请先移除全部书架"));
      return;
    }
    const approved = await confirm({
      title: activeIsCollection ? '删除合集' : '删除书架',
      description: activeIsCollection
        ? `删除合集“${activeShelf.name}”？`
        : activeIsSmart
        ? `删除智能书架“${activeShelf.name}”？自动收录规则会被删除，但图书仍会保留在书库中。`
        : `删除书架“${activeShelf.name}”？书架中的图书仍会保留在书库中。`,
      confirmLabel: activeIsCollection ? '删除合集' : '删除书架',
      tone: 'danger'
    });
    if (!approved) return;
    setSaving(true);
    setError('');
    try {
      await deleteShelfById(activeShelf.id);
      await loadShelves();
      window.dispatchEvent(new Event('shuku:shelves-changed'));
      toast.success(activeIsCollection ? '合集已删除' : '书架已删除');
      router.replace('/shelves', { scroll: false });
    } catch (reason) {
      const nextError = shelfErrorMessage(reason, '删除书架失败');
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
      {!editing && activeShelf ? <Button icon={Edit3} onClick={() => router.push(`/shelves?shelf=${encodeURIComponent(activeShelf.id)}&edit=1`, { scroll: false })}>{activeIsCollection ? <I18nText>管理合集</I18nText> : <I18nText>管理书架</I18nText>}</Button> : null}
      {editing ? <Button icon={Save} loading={saving} loadingText={i18nAttribute("保存中")} disabled={detailLoading || (activeIsSmart && incompleteSmartFilterCount > 0)} onClick={saveShelf}>{activeIsNew ? i18nAttribute(activeIsCollection ? "创建合集" : activeIsSmart ? "创建智能书架" : "创建书架") : i18nAttribute("保存更改")}</Button> : null}
    </div>
  ) : <Button icon={Plus} onClick={() => router.push('/shelves?create=1', { scroll: false })}><I18nText>创建书架</I18nText></Button>;

  return (
    <div className="shuku-content-frame space-y-6">
      <PageTitle
        title={activeIsNew ? i18nAttribute("创建书架") : activeShelf ? activeShelf.name : activeId ? i18nAttribute("书架详情") : i18nAttribute("书架")}
        titleMeta={activeShelf ? (
          <span className="flex shrink-0 items-center gap-2 text-[13px] text-[#8A847E] sm:text-[15px]">
            <span>
              {activeIsCollection
                ? <>{activeShelf.shelfCount ?? 0} <I18nText>个书架</I18nText></>
                : <>{activeShelf.bookCount ?? 0} <I18nText>本</I18nText></>}
            </span>
          </span>
        ) : undefined}
        translateTitle={!activeShelf}
        desc={activeIsNew
          ? activeIsCollection
            ? i18nAttribute("创建合集，把相关书架集中整理在一起。")
            : activeIsSmart
            ? i18nAttribute("设置自动收录条件，书架会随图书信息变化自动更新。")
            : i18nAttribute("填写基本信息，也可以现在就加入第一批图书。")
          : activeShelf
            ? activeShelf.description ?? ''
            : i18nAttribute("创建自定义书架，按主题、系列或阅读计划整理图书。")}
        translateDescription={!activeShelf}
        action={pageAction}
      />

      {activeShelf?.rulesStatus === 'UNSUPPORTED' ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900" role="status">
          <div className="font-semibold"><I18nText>这个智能书架包含已停止支持的筛选条件</I18nText></div>
          <div className="mt-1"><I18nText>请编辑书架并删除这些条件后再保存。</I18nText> <span data-i18n-skip>{activeShelf.unsupportedRuleFields.join(', ')}</span></div>
        </div>
      ) : null}

      {error ? <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div> : null}

      {activeId && detailLoading ? <div className="shuku-loading-panel p-6 text-sm" role="status" aria-live="polite"><I18nText>正在读取书架详情...</I18nText></div> : null}

      {activeId && !detailLoading && editing ? (
        <section className="rounded-[24px] border border-[#E5DED8] bg-white p-5 shadow-[0_12px_36px_rgba(63,48,40,0.06)] md:p-6">
          <div className="flex flex-col gap-3 border-b border-[#EEE8E3] pb-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2 font-semibold text-[#2A2825]"><Edit3 size={17} /> {activeIsNew ? i18nAttribute("书架信息") : i18nAttribute("编辑书架")}</div>
              <div className="mt-1 text-sm text-[#7C756F]">
                {activeIsNew && activeIsSmart
                  ? i18nAttribute("使用与全部图书相同的筛选条件，匹配结果会自动更新。")
                  : activeIsCollection
                    ? i18nAttribute("选择要包含的书架，合集本身不能包含图书。")
                  : activeIsSmart
                    ? i18nAttribute("可以修改基本信息并查看自动收录条件；图书由规则自动管理。")
                    : i18nAttribute("勾选或移除图书后，点击“{value0}”统一生效。", { value0: activeIsNew ? '创建书架' : '保存更改' })}
              </div>
            </div>
            <Badge>
              {activeIsCollection
                ? <>{selectedMemberShelfIds.length} <I18nText>个书架</I18nText></>
                : <>{activeIsNew && activeIsSmart ? previewTotal : activeIsSmart ? activeShelf?.bookCount ?? 0 : selectedBookIds.length} <I18nText>本图书</I18nText></>}
            </Badge>
          </div>

          <div className="mt-5 grid gap-6 xl:grid-cols-[minmax(0,1fr)_390px]">
            <div className="space-y-6">
              {activeIsNew ? (
                <fieldset>
                  <legend className="text-sm font-semibold text-[#2A2825]"><I18nText>书架类型</I18nText></legend>
                  <div className="mt-3 grid gap-3 sm:grid-cols-3">
                    <button
                      type="button"
                      aria-pressed={draftKind === 'STATIC'}
                      onClick={() => setDraftKind('STATIC')}
                      className={cn(
                        'flex min-h-20 items-center gap-3 rounded-2xl border px-4 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-[#F6B7A5]',
                        draftKind === 'STATIC'
                          ? 'border-[#F0AA96] bg-[#FFF8F5] ring-2 ring-[#FBE1D9]'
                          : 'border-[#E4DED8] bg-white hover:border-[#D7CEC7]'
                      )}
                    >
                      <BookOpen size={20} className={draftKind === 'STATIC' ? 'text-[#D94724]' : 'text-[#817A74]'} />
                      <span>
                        <span className="block text-sm font-semibold text-[#2A2825]"><I18nText>普通书架</I18nText></span>
                        <span className="mt-1 block text-xs text-[#817A74]"><I18nText>手动选择图书加入</I18nText></span>
                      </span>
                    </button>
                    <button
                      type="button"
                      aria-pressed={draftKind === 'SMART'}
                      onClick={() => setDraftKind('SMART')}
                      className={cn(
                        'flex min-h-20 items-center gap-3 rounded-2xl border px-4 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-[#F6B7A5]',
                        draftKind === 'SMART'
                          ? 'border-[#F0AA96] bg-[#FFF8F5] ring-2 ring-[#FBE1D9]'
                          : 'border-[#E4DED8] bg-white hover:border-[#D7CEC7]'
                      )}
                    >
                      <Sparkles size={20} className={draftKind === 'SMART' ? 'text-[#D94724]' : 'text-[#817A74]'} />
                      <span>
                        <span className="block text-sm font-semibold text-[#2A2825]"><I18nText>智能书架</I18nText></span>
                        <span className="mt-1 block text-xs text-[#817A74]"><I18nText>图书会按条件自动加入或移出</I18nText></span>
                      </span>
                    </button>
                    <button
                      type="button"
                      aria-pressed={draftKind === 'COLLECTION'}
                      onClick={() => setDraftKind('COLLECTION')}
                      className={cn(
                        'flex min-h-20 items-center gap-3 rounded-2xl border px-4 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-[#F6B7A5]',
                        draftKind === 'COLLECTION'
                          ? 'border-[#F0AA96] bg-[#FFF8F5] ring-2 ring-[#FBE1D9]'
                          : 'border-[#E4DED8] bg-white hover:border-[#D7CEC7]'
                      )}
                    >
                      <Folders size={20} className={draftKind === 'COLLECTION' ? 'text-[#D94724]' : 'text-[#817A74]'} />
                      <span>
                        <span className="block text-sm font-semibold text-[#2A2825]"><I18nText>书架合集</I18nText></span>
                        <span className="mt-1 block text-xs text-[#817A74]"><I18nText>集中整理多个书架</I18nText></span>
                      </span>
                    </button>
                  </div>
                </fieldset>
              ) : null}

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

              {activeIsCollection ? (
                <fieldset>
                  <legend className="text-sm font-semibold text-[#2A2825]"><I18nText>合集中的书架</I18nText></legend>
                  <div className="mt-1 text-xs leading-5 text-[#8A837D]"><I18nText>普通书架和智能书架可以同时加入多个合集。</I18nText></div>
                  {memberShelfOptions.length > 0 ? (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      {memberShelfOptions.map((shelf) => {
                        const checked = selectedMemberShelfIds.includes(shelf.id);
                        return (
                          <label key={shelf.id} className={cn('flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition', checked ? 'border-[#F0AA96] bg-[#FFF8F5]' : 'border-[#E5DED8] hover:border-[#D7CEC7]')}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(event) => setSelectedMemberShelfIds((current) => event.target.checked ? [...new Set([...current, shelf.id])] : current.filter((id) => id !== shelf.id))}
                              className="h-4 w-4 accent-[#E94B27]"
                            />
                            {shelf.kind === 'SMART' ? <Sparkles size={17} className="text-amber-600" /> : <BookOpen size={17} className="text-[#817A74]" />}
                            <span className="min-w-0 flex-1">
                              <span data-i18n-skip className="block truncate text-sm font-medium text-[#2A2825]">{shelf.name}</span>
                              <span className="mt-0.5 block text-xs text-[#8A837D]">{shelf.bookCount ?? 0} <I18nText>本图书</I18nText></span>
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="mt-3 rounded-2xl border border-dashed border-[#DCD5CE] bg-[#FAF8F6] px-4 py-6 text-center text-sm text-[#817A74]"><I18nText>暂无可加入合集的书架</I18nText></div>
                  )}
                </fieldset>
              ) : (
                <fieldset>
                  <legend className="text-sm font-semibold text-[#2A2825]"><I18nText>所属合集</I18nText></legend>
                  <div className="mt-1 text-xs leading-5 text-[#8A837D]"><I18nText>加入合集后，这个书架会从侧栏顶层隐藏，并可从每个所属合集进入。</I18nText></div>
                  {collectionOptions.length > 0 ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {collectionOptions.map((collection) => {
                        const checked = selectedCollectionIds.includes(collection.id);
                        return (
                          <label key={collection.id} className={cn('inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-xl border px-3 text-sm transition', checked ? 'border-[#F0AA96] bg-[#FFF8F5] text-[#B63D23]' : 'border-[#E5DED8] text-[#5F5954] hover:border-[#D7CEC7]')}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(event) => setSelectedCollectionIds((current) => event.target.checked ? [...new Set([...current, collection.id])] : current.filter((id) => id !== collection.id))}
                              className="h-4 w-4 accent-[#E94B27]"
                            />
                            <Folders size={15} />
                            <span data-i18n-skip>{collection.name}</span>
                          </label>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="mt-3 text-sm text-[#918A84]"><I18nText>还没有可加入的合集。</I18nText></div>
                  )}
                </fieldset>
              )}

              {activeIsCollection ? null : activeIsSmart ? (
                <div className="border-t border-[#EEE8E3] pt-3">
                  {filterSchemaError ? (
                    <div className="mt-3 rounded-2xl border border-red-100 bg-red-50 px-4 py-5 text-sm text-red-700" role="alert">
                      {filterSchemaError}
                    </div>
                  ) : (
                    <SmartFilterBuilder
                      fields={smartFilterFields}
                      rules={smartFilterRules}
                      loading={filterSchemaLoading || !filterSchemaLoaded}
                      onChange={setSmartFilterRules}
                    />
                  )}
                  {incompleteSmartFilterCount > 0 ? (
                    <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" role="status">
                      {i18nAttribute("还有 {value0} 条条件没有填写完整，请补全后再创建。", { value0: incompleteSmartFilterCount })}
                    </div>
                  ) : null}
                </div>
              ) : activeIsSmart ? (
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

            {!activeIsSmart && !activeIsCollection ? <aside className="self-start rounded-[20px] bg-[#F6F3F0] p-4 xl:sticky xl:top-6">
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
                        <div className="mt-1 line-clamp-1 text-xs text-[#8B847E]">{book.author || i18nAttribute("未知作者")} · {mediaKindsLabel(book.availableMediaKinds ?? [], locale)}</div>
                      </div>
                      {checked ? <Check size={16} className="shrink-0 text-[#D94724]" /> : null}
                    </label>
                  );
                })}
              </div>
            </aside> : activeIsCollection ? (
              <aside className="self-start rounded-[20px] border border-[#E5DED8] bg-[#FAF8F6] p-4 text-sm leading-6 text-[#6F6963] xl:sticky xl:top-6">
                <div className="flex items-center gap-2 font-semibold text-[#2A2825]"><Folders size={17} /><I18nText>关于书架合集</I18nText></div>
                <div className="mt-2"><I18nText>合集只整理书架，不直接包含图书。一个书架可以加入多个合集。</I18nText></div>
              </aside>
            ) : activeIsNew ? (
              <aside className="self-start overflow-hidden rounded-[20px] border border-[#E5DED8] bg-[#FAF8F6] xl:sticky xl:top-6">
                <div className="flex items-start justify-between gap-3 border-b border-[#E9E2DC] px-4 py-4">
                  <div>
                    <div className="text-sm font-semibold text-[#2A2825]"><I18nText>匹配预览</I18nText></div>
                    <div className="mt-1 text-xs leading-5 text-[#827B75]"><I18nText>筛选条件修改后实时更新</I18nText></div>
                  </div>
                  <Badge>{previewTotal} <I18nText>本图书</I18nText></Badge>
                </div>
                <div className="space-y-2 p-4" aria-live="polite">
                  {previewLoading ? (
                    <div className="flex min-h-28 items-center justify-center text-sm text-[#8D857E]" role="status">
                      <Loader2 size={16} className="mr-2 animate-spin" />
                      <I18nText>正在更新匹配结果...</I18nText>
                    </div>
                  ) : previewError ? (
                    <div className="rounded-xl border border-red-100 bg-red-50 px-3 py-4 text-sm text-red-700">{previewError}</div>
                  ) : previewBooks.length > 0 ? previewBooks.map((book) => (
                    <div key={book.id} className="flex items-center gap-3 rounded-xl border border-[#E8E1DB] bg-white p-2.5">
                      <Cover book={book} className="h-[72px] w-12 shrink-0 rounded-lg" small />
                      <div data-i18n-skip className="min-w-0">
                        <div className="line-clamp-1 text-sm font-semibold text-[#2A2825]">{book.title}</div>
                        <div className="mt-1 line-clamp-1 text-xs text-[#8B847E]">{book.author || i18nAttribute("未知作者")}</div>
                      </div>
                    </div>
                  )) : (
                    <div className="rounded-xl border border-dashed border-[#DCD5CE] bg-white/70 px-4 py-6 text-center">
                      <BookOpen size={20} className="mx-auto text-[#B3AAA2]" />
                      <div className="mt-2 text-sm font-medium text-[#5F5954]"><I18nText>暂无图书符合条件</I18nText></div>
                      <div className="mt-1 text-xs leading-5 text-[#918A84]"><I18nText>调整筛选条件后再试试。</I18nText></div>
                    </div>
                  )}
                  {!previewLoading && !previewError && previewTotal > 0 ? (
                    <button
                      type="button"
                      onClick={() => router.push(`/library${smartFilterQuery ? `?filters=${encodeURIComponent(smartFilterQuery)}` : ''}`)}
                      className="mt-2 inline-flex h-9 w-full items-center justify-center rounded-lg text-sm font-medium text-[#D94724] outline-none transition hover:bg-[#FFF0EA] focus-visible:ring-2 focus-visible:ring-[#F6B7A5]"
                    >
                      <I18nText>查看全部匹配图书</I18nText>
                    </button>
                  ) : null}
                </div>
                <div className="border-t border-[#E9E2DC] px-4 py-3 text-xs leading-5 text-[#817A74]">
                  <I18nText>创建后，匹配图书会自动加入或移出书架。</I18nText>
                </div>
              </aside>
            ) : (
              <aside className="self-start rounded-[20px] border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900 xl:sticky xl:top-6">
                <div className="font-semibold"><I18nText>图书自动管理</I18nText></div>
                <div className="mt-1"><I18nText>智能书架会随图书信息和阅读状态变化自动更新，因此不提供手动添加或移除。</I18nText></div>
              </aside>
            )}
          </div>

          {!activeIsNew ? (
            <div className="mt-6 flex flex-col gap-3 border-t border-[#EEE8E3] pt-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm text-[#817A74]">
                {activeIsCollection
                  ? (activeShelf?.shelfCount ?? 0) > 0
                    ? i18nAttribute("合集仍有书架，移除全部成员后才能删除。")
                    : i18nAttribute("空合集可以安全删除，不会影响任何书架。")
                  : activeIsSmart
                    ? i18nAttribute("删除智能书架只会删除自动收录规则，不会删除任何图书。")
                    : i18nAttribute("不再需要这个分类时，可以只删除书架，图书会继续保留在书库。")}
              </div>
              <Button variant="danger" icon={Trash2} disabled={saving || (activeIsCollection && (activeShelf?.shelfCount ?? 0) > 0)} onClick={deleteShelf}>{activeIsCollection ? <I18nText>删除合集</I18nText> : <I18nText>删除书架</I18nText>}</Button>
            </div>
          ) : null}
        </section>
      ) : null}

      {activeId && !detailLoading && !editing && activeShelf ? (
        <section>
          {activeIsCollection && memberShelves.length > 0 ? (
            <>
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {memberShelves.map((member) => (
                  <ShelfCard
                    key={member.id}
                    shelf={member}
                    onOpen={() => router.push(`/shelves?shelf=${encodeURIComponent(member.id)}`, { scroll: false })}
                  />
                ))}
              </div>
              <ShelfLoadStatus
                sentinelRef={loadMoreRef}
                loading={loadingMore}
                loaded={memberShelves.length}
                total={activeShelf.total ?? activeShelf.shelfCount ?? 0}
                unit="shelves"
              />
            </>
          ) : activeIsCollection ? (
            <div className="rounded-[24px] border border-dashed border-[#DCD5CE] bg-[#FAF8F6] px-6 py-12 text-center">
              <Folders size={30} className="mx-auto text-[#B4ABA4]" />
              <div className="mt-4 font-semibold text-[#403C38]"><I18nText>这个合集还没有书架</I18nText></div>
              <div className="mt-1 text-sm text-[#8D857E]"><I18nText>打开管理页，选择想放进合集的普通或智能书架。</I18nText></div>
              <Button className="mt-5" icon={Plus} onClick={() => router.push(`/shelves?shelf=${encodeURIComponent(activeShelf.id)}&edit=1`, { scroll: false })}><I18nText>添加书架</I18nText></Button>
            </div>
          ) : shelfBooks.length > 0 ? (
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
                total={activeShelf.total ?? activeShelf.bookCount ?? 0}
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
            <ShelfCard
              key={shelf.id}
              shelf={shelf}
              onOpen={() => router.push(`/shelves?shelf=${encodeURIComponent(shelf.id)}`, { scroll: false })}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ShelfCard({
  shelf,
  onOpen
}: {
  shelf: ShelfView;
  onOpen: () => void;
}) {
  const { t: i18nAttribute } = useAttributeI18n();

  return (
    <button
      type="button"
      onClick={onOpen}
      className="group rounded-[22px] border border-[#E5DED8] bg-white p-4 text-left outline-none transition duration-200 hover:-translate-y-0.5 hover:border-[#E9B7A7] hover:shadow-[0_12px_28px_rgba(73,52,43,0.09)] focus-visible:ring-4 focus-visible:ring-[#FBE1D9]"
    >
      <div className="flex h-32 items-end overflow-hidden rounded-[16px] bg-[#F4F0EC] px-5 pb-3">
        {shelf.kind === 'COLLECTION' ? (
          <div className="flex w-full flex-col items-center justify-center self-center text-[#A09790]">
            <Folders size={34} />
            <span className="mt-2 text-sm">{shelf.shelfCount ?? 0} <I18nText>个书架</I18nText></span>
          </div>
        ) : (
          <>
            {(shelf.books ?? []).slice(0, 3).map((book, index) => (
              <Cover key={`${book.id}-${index}`} book={book} className={cn('h-24 w-16 shrink-0 shadow-md transition duration-200 group-hover:-translate-y-1', index > 0 && '-ml-3')} small />
            ))}
            {(shelf.books ?? []).length === 0 ? <div className="flex w-full items-center justify-center self-center text-sm text-[#A09790]"><BookOpen size={17} className="mr-2" /> <I18nText>暂无图书</I18nText></div> : null}
          </>
        )}
      </div>
      <div className="mt-4">
        <div className="flex items-center gap-2">
          <div data-i18n-skip className="line-clamp-1 font-semibold text-[#2A2825]">{shelf.name}</div>
          {shelf.kind === 'SMART'
              ? <Badge tone="amber"><I18nText>智能</I18nText></Badge>
              : shelf.kind === 'COLLECTION'
                ? <Badge><I18nText>合集</I18nText></Badge>
                : null}
        </div>
        <div data-i18n-skip={shelf.description ? '' : undefined} className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 text-[#817A74]">
          {shelf.description || i18nAttribute(shelf.kind === 'COLLECTION' ? "书架合集" : "自定义书架")}
        </div>
        <div className="mt-3 flex items-center justify-between border-t border-[#EEE8E3] pt-3 text-xs text-[#938B84]">
          <span>{shelf.kind === 'COLLECTION' ? <>{shelf.shelfCount ?? 0} <I18nText>个书架</I18nText></> : <>{shelf.bookCount ?? 0} <I18nText>本图书</I18nText></>}</span>
          <span className="font-medium text-[#D94724] transition group-hover:translate-x-0.5">{shelf.kind === 'COLLECTION' ? <I18nText>打开合集 →</I18nText> : <I18nText>打开书架 →</I18nText>}</span>
        </div>
      </div>
    </button>
  );
}

function ShelfLoadStatus({
  sentinelRef,
  loading,
  loaded,
  total,
  unit = 'books'
}: {
  sentinelRef: { current: HTMLDivElement | null };
  loading: boolean;
  loaded: number;
  total: number;
  unit?: 'books' | 'shelves';
}) {
  const { t: i18nAttribute } = useAttributeI18n();

  return (
    <div ref={sentinelRef} className="flex min-h-20 items-center justify-center py-5 text-xs tabular-nums text-[#8A847E]" role="status" aria-live="polite">
      {loading
        ? <><Loader2 size={15} className="mr-2 animate-spin" />{unit === 'shelves' ? <I18nText>正在加载更多书架...</I18nText> : <I18nText>正在加载更多图书...</I18nText>}</>
        : unit === 'shelves'
          ? i18nAttribute("已加载 {value0} / {value1} 个书架", { value0: loaded, value1: total })
          : i18nAttribute("已加载 {value0} / {value1} 本", { value0: loaded, value1: total })}
    </div>
  );
}
