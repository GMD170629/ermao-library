'use client';

import { ChevronLeft, ChevronRight, Edit3, GitMerge, Loader2, Search, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useToast } from '../../components/ui/feedback';
import { Select } from '../../components/ui/select';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type Kind = 'AUTHOR' | 'TAG' | 'SERIES';
type Category = { id: string; kind: Kind; name: string; aliases: string[]; bookCount: number };
type CategoryPage = { categories: Category[]; page: number; pageSize: number; total: number; totalPages: number };
type ApiPayload<T> = { ok: boolean; data?: T; error?: { message: string } };
const tabs: Array<{ key: Kind; label: string }> = [
  { key: 'AUTHOR', label: '作者' }, { key: 'TAG', label: '标签' }, { key: 'SERIES', label: '丛书' }
];

async function payload<T>(response: Response, fallback: string) {
  const result = await response.json().catch(() => null) as ApiPayload<T> | null;
  if (!response.ok || !result?.ok) throw new Error(result?.error?.message ?? fallback);
  return result.data as T;
}

export function ClassificationManagementPanel() {
  const { t: i18nAttribute } = useAttributeI18n();
  const [kind, setKind] = useState<Kind>('AUTHOR');
  const [items, setItems] = useState<Category[]>([]);
  const [selectedItems, setSelectedItems] = useState<Category[]>([]);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState('20');
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [renameItem, setRenameItem] = useState<Category | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [mergeOpen, setMergeOpen] = useState(false);
  const [targetId, setTargetId] = useState('');
  const [deleteItem, setDeleteItem] = useState<Category | null>(null);
  const [error, setError] = useState('');
  const toast = useToast();

  const load = useCallback(async (nextKind = kind, nextSearch = search, nextPage = page, nextPageSize = pageSize) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ kind: nextKind, page: String(nextPage), pageSize: nextPageSize });
      if (nextSearch.trim()) params.set('search', nextSearch.trim());
      const data = await payload<CategoryPage>(await fetch(`/api/library/categories?${params}`), '读取分类失败');
      setItems(data.categories);
      setPage(data.page);
      setTotal(data.total);
      setTotalPages(data.totalPages);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取分类失败');
    } finally {
      setLoading(false);
    }
  }, [kind, page, pageSize, search]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(kind, search, page, pageSize), 180);
    return () => window.clearTimeout(timer);
  }, [kind, load, page, pageSize, search]);

  const selectedIds = useMemo(() => selectedItems.map((item) => item.id), [selectedItems]);

  function changeKind(nextKind: Kind) {
    setKind(nextKind);
    setSelectedItems([]);
    setSearch('');
    setPage(1);
  }

  async function rename() {
    if (!renameItem || !renameValue.trim()) return;
    setSaving(true);
    try {
      await payload(await fetch(`/api/library/categories/${renameItem.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: renameValue.trim() }) }), '重命名失败');
      toast.success('分类已重命名');
      setRenameItem(null);
      setSelectedItems([]);
      await load();
    } catch (reason) {
      toast.error('重命名失败', reason instanceof Error ? reason.message : '重命名失败');
    } finally { setSaving(false); }
  }

  function openMerge() {
    if (selectedItems.length < 2) return;
    setTargetId(selectedItems[0].id);
    setMergeOpen(true);
  }

  async function merge() {
    if (!targetId) return;
    setSaving(true);
    try {
      await payload(await fetch('/api/library/categories/merge', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, targetId, sourceIds: selectedIds.filter((id) => id !== targetId) })
      }), '合并分类失败');
      toast.success('分类已合并');
      setSelectedItems([]);
      setMergeOpen(false);
      await load();
    } catch (reason) {
      toast.error('合并失败', reason instanceof Error ? reason.message : '合并分类失败');
    } finally { setSaving(false); }
  }

  async function removeCategory() {
    if (!deleteItem) return;
    setSaving(true);
    try {
      await payload(await fetch(`/api/library/categories/${deleteItem.id}`, { method: 'DELETE' }), '删除分类失败');
      toast.success('分类及对应元数据已删除');
      setDeleteItem(null);
      setSelectedItems((current) => current.filter((item) => item.id !== deleteItem.id));
      await load();
    } catch (reason) {
      toast.error('删除失败', reason instanceof Error ? reason.message : '删除分类失败');
    } finally { setSaving(false); }
  }

  function deleteDescription(item: Category) {
    if (item.kind === 'AUTHOR') {
      return i18nAttribute('将从 {value0} 本图书中移除作者“{value1}”。没有其他作者的图书会改为“未知作者”。', { value0: item.bookCount, value1: item.name });
    }
    if (item.kind === 'TAG') {
      return i18nAttribute('将从 {value0} 本图书中移除标签“{value1}”。其他标签不会受到影响。', { value0: item.bookCount, value1: item.name });
    }
    if (item.kind === 'SERIES') {
      return i18nAttribute('将清除 {value0} 本图书的丛书“{value1}”及对应丛书序号。', { value0: item.bookCount, value1: item.name });
    }
    return i18nAttribute('将从 {value0} 本图书的相关卷册中清除出版社“{value1}”。', { value0: item.bookCount, value1: item.name });
  }

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-black/[0.07] bg-white/60 p-5">
        <h2 className="text-base font-semibold text-[#2C2926]"><I18nText>分类治理</I18nText></h2>
        <p className="mt-1 text-sm leading-6 text-[#817B75]"><I18nText>统一作者、标签、丛书和出版社命名。作品字段与卷册出版信息会按各自作用域更新。</I18nText></p>
        <div className="mt-4 flex flex-wrap gap-2">
          {tabs.map((tab) => <button key={tab.key} type="button" onClick={() => changeKind(tab.key)} className={cn('rounded-xl px-4 py-2 text-sm transition', kind === tab.key ? 'bg-[#F9DED4] font-medium text-[#D7462B]' : 'bg-black/[0.035] text-[#6F6963] hover:bg-black/[0.06]')}>{i18nAttribute(tab.label)}</button>)}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex h-11 min-w-[260px] items-center gap-2 rounded-xl border border-black/[0.09] bg-white px-3">
          <Search size={16} className="text-[#8A847E]" /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); setSelectedItems([]); }} placeholder={i18nAttribute("搜索{value0}", { value0: i18nAttribute(tabs.find((tab) => tab.key === kind)?.label ?? '') })} className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
        </label>
        <Button icon={GitMerge} disabled={selectedItems.length < 2} onClick={openMerge}><I18nText>合并所选（</I18nText>{selectedItems.length}）</Button>
      </div>
      {error ? <div className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
      <div className="overflow-hidden rounded-2xl border border-black/[0.07] bg-white/65">
        {loading ? <div className="flex min-h-44 items-center justify-center text-sm text-[#817B75]"><Loader2 size={17} className="mr-2 animate-spin" /><I18nText>正在读取分类…</I18nText></div> : items.length === 0 ? <div className="flex min-h-44 items-center justify-center text-sm text-[#817B75]"><I18nText>没有匹配的分类</I18nText></div> : (
          <div className="divide-y divide-black/[0.055]">
            {items.map((item) => <div key={item.id} className="flex items-center gap-3 px-4 py-3.5">
              <input type="checkbox" checked={selectedIds.includes(item.id)} onChange={(event) => setSelectedItems((current) => event.target.checked ? [...current.filter((selectedItem) => selectedItem.id !== item.id), item] : current.filter((selectedItem) => selectedItem.id !== item.id))} className="h-4 w-4 accent-[#EF4D2F]" />
              <div className="min-w-0 flex-1"><div className="font-medium text-[#34312E]">{item.name}</div>{item.aliases.length ? <div className="mt-0.5 truncate text-xs text-[#948E88]"><I18nText>曾用名：</I18nText>{item.aliases.join('、')}</div> : null}</div>
              <div className="text-sm tabular-nums text-[#817B75]">{item.bookCount} <I18nText>本</I18nText></div>
              <Button variant="ghost" icon={Edit3} className="px-3" onClick={() => { setRenameItem(item); setRenameValue(item.name); }}><I18nText>重命名</I18nText></Button>
              <Button variant="ghost" icon={Trash2} className="px-3 text-red-600 hover:bg-red-50 hover:text-red-700" onClick={() => setDeleteItem(item)}><I18nText>删除</I18nText></Button>
            </div>)}
          </div>
        )}
        {!loading && total > 0 ? (
          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-black/[0.07] px-4 py-3 text-sm text-[#77716A]">
            <div className="flex items-center gap-3">
              <span><I18nText>共 </I18nText>{total} <I18nText>项</I18nText></span>
              <Select
                value={pageSize}
                onChange={(value) => { setPageSize(value); setPage(1); }}
                ariaLabel={i18nAttribute("每页显示数量")}
                options={[
                  { value: '20', label: '每页 20 项' },
                  { value: '50', label: '每页 50 项' },
                  { value: '100', label: '每页 100 项' }
                ]}
                size="sm"
                align="left"
                className="min-w-[118px]"
              />
            </div>
            <nav className="flex items-center gap-2" aria-label={i18nAttribute("分类治理分页")}>
              <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40" aria-label={i18nAttribute("上一页")}><ChevronLeft size={16} /></button>
              <span className="min-w-16 text-center text-[#4F4A45]">{page} / {totalPages}</span>
              <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((current) => Math.min(totalPages, current + 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40" aria-label={i18nAttribute("下一页")}><ChevronRight size={16} /></button>
            </nav>
          </footer>
        ) : null}
      </div>

      {renameItem ? <Modal title={i18nAttribute("重命名“{value0}”", { value0: renameItem.name })} onClose={() => setRenameItem(null)}>
        <input autoFocus value={renameValue} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void rename(); }} className="h-11 w-full rounded-xl border border-black/[0.1] bg-white px-4 outline-none focus:border-[#E9A18D]" />
        <div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={() => setRenameItem(null)}><I18nText>取消</I18nText></Button><Button loading={saving} onClick={() => void rename()}><I18nText>保存</I18nText></Button></div>
      </Modal> : null}

      {mergeOpen ? <Modal title={i18nAttribute("合并 {value0} 个分类", { value0: selectedItems.length })} onClose={() => setMergeOpen(false)}>
        <p className="mb-4 text-sm leading-6 text-[#746E68]"><I18nText>选择保留的规范名称，其余名称会作为别名保留，关联作品不会丢失。</I18nText></p>
        <Select value={targetId} options={selectedItems.map((item) => ({ value: item.id, label: `${item.name}（${item.bookCount} 本）`, translate: false }))} onChange={setTargetId} ariaLabel={i18nAttribute("保留的分类名称")} className="w-full" />
        <div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={() => setMergeOpen(false)}><I18nText>取消</I18nText></Button><Button loading={saving} icon={GitMerge} onClick={() => void merge()}><I18nText>确认合并</I18nText></Button></div>
      </Modal> : null}

      {deleteItem ? <Modal title={i18nAttribute("删除“{value0}”", { value0: deleteItem.name })} onClose={() => setDeleteItem(null)}>
        <p className="rounded-2xl bg-red-50 px-4 py-3 text-sm leading-6 text-red-800">{deleteDescription(deleteItem)}</p>
        <p className="mt-3 text-sm leading-6 text-[#746E68]"><I18nText>此操作会同步修改图书元数据，请确认后再继续。</I18nText></p>
        <div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={() => setDeleteItem(null)}><I18nText>取消</I18nText></Button><Button variant="danger" loading={saving} icon={Trash2} onClick={() => void removeCategory()}><I18nText>确认删除</I18nText></Button></div>
      </Modal> : null}
    </div>
  );
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return <div className="fixed inset-0 z-[90] flex items-end justify-center bg-[#241F1C]/35 p-0 backdrop-blur-[2px] md:items-center md:p-6" role="dialog" aria-modal="true"><div className="w-full max-w-md rounded-t-3xl bg-[#FFFEFC] p-6 shadow-2xl md:rounded-3xl"><div className="mb-5 flex items-center justify-between"><h3 className="text-lg font-semibold text-[#2E2A27]">{title}</h3><button type="button" onClick={onClose} className="text-sm text-[#817B75]"><I18nText>关闭</I18nText></button></div>{children}</div></div>;
}
