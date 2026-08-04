'use client';

import { ArrowDown, ArrowUp, ArrowUpDown, Eye, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { useEffect, useRef } from 'react';
import { mediaKindsLabel, type ManagementWorkSummary } from '../../features/library/public';
import { useI18n } from '../../i18n/provider';
import { Badge } from '../ui/badge';
import type { BadgeTone } from '../ui/badge';
import { Button } from '../ui/button';
import { Cover } from './cover';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type SortDirection = 'asc' | 'desc';

function localDateLabel(value: string | null | undefined, fallback: string, locale: string) {
  if (!value) return fallback;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? fallback : date.toLocaleDateString(locale);
}

export function BookTable({
  books,
  onDelete,
  selectable = false,
  selectedIds = [],
  onSelect,
  onSelectAll,
  onSelectionChange,
  onContextMenu,
  sort,
  sortDirection = 'asc',
  onSort
}: {
  books: ManagementWorkSummary[];
  onDelete?: (book: ManagementWorkSummary) => void;
  selectable?: boolean;
  selectedIds?: string[];
  onSelect?: (book: ManagementWorkSummary) => void;
  onSelectAll?: (selected: boolean) => void;
  onSelectionChange?: (ids: string[]) => void;
  onContextMenu?: (book: ManagementWorkSummary, position: { x: number; y: number }) => void;
  sort?: string;
  sortDirection?: SortDirection;
  onSort?: (sort: string, direction: SortDirection) => void;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  const router = useRouter();
  const { locale } = useI18n();
  const allSelected = books.length > 0 && books.every((book) => selectedIds.includes(book.id));
  const selectedRef = useRef(new Set(selectedIds));
  const anchorIndexRef = useRef<number | null>(null);
  const dragRef = useRef<{ active: boolean; mode: 'select' | 'deselect'; visited: Set<string> }>({ active: false, mode: 'select', visited: new Set() });

  useEffect(() => {
    selectedRef.current = new Set(selectedIds);
  }, [selectedIds]);

  useEffect(() => {
    function stopDrag() {
      if (!dragRef.current.active) return;
      dragRef.current.active = false;
      dragRef.current.visited.clear();
      document.body.style.removeProperty('user-select');
    }
    window.addEventListener('mouseup', stopDrag);
    window.addEventListener('blur', stopDrag);
    return () => {
      window.removeEventListener('mouseup', stopDrag);
      window.removeEventListener('blur', stopDrag);
      document.body.style.removeProperty('user-select');
    };
  }, []);

  function commitSelection(next: Set<string>) {
    selectedRef.current = next;
    onSelectionChange?.(books.filter((book) => next.has(book.id)).map((book) => book.id));
  }

  function applyDragSelection(bookId: string) {
    const drag = dragRef.current;
    if (!drag.active || drag.visited.has(bookId)) return;
    drag.visited.add(bookId);
    const next = new Set(selectedRef.current);
    if (drag.mode === 'select') next.add(bookId);
    else next.delete(bookId);
    commitSelection(next);
  }

  function beginRowSelection(event: ReactMouseEvent<HTMLTableRowElement>, book: ManagementWorkSummary, index: number) {
    if (!selectable || event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('button, a, input, select, textarea, [data-selection-ignore="true"]')) return;
    event.preventDefault();
    if (event.shiftKey && anchorIndexRef.current !== null) {
      const start = Math.min(anchorIndexRef.current, index);
      const end = Math.max(anchorIndexRef.current, index);
      const next = new Set(selectedRef.current);
      books.slice(start, end + 1).forEach((item) => next.add(item.id));
      commitSelection(next);
      return;
    }
    anchorIndexRef.current = index;
    const mode = selectedRef.current.has(book.id) ? 'deselect' : 'select';
    dragRef.current = { active: true, mode, visited: new Set() };
    document.body.style.userSelect = 'none';
    applyDragSelection(book.id);
  }

  function openContextMenu(event: ReactMouseEvent<HTMLElement>, book: ManagementWorkSummary) {
    if (!selectable || !onContextMenu) return;
    event.preventDefault();
    if (!selectedRef.current.has(book.id)) commitSelection(new Set([book.id]));
    onContextMenu(book, { x: event.clientX, y: event.clientY });
  }

  function mediaLabel(book: ManagementWorkSummary) {
    return mediaKindsLabel(book.availableMediaKinds, locale) || '—';
  }

  function statusLabel(book: ManagementWorkSummary) {
    const kinds = book.availableMediaKinds;
    const status = book.statusValue;
    if (kinds.length !== 1) return status === 'FINISHED' ? '已完成' : status === 'READING' ? '进行中' : '未开始';
    if (kinds[0] === 'AUDIOBOOK') return status === 'FINISHED' ? '听完' : status === 'READING' ? '在听' : '未听';
    if (kinds[0] === 'COMIC') return status === 'FINISHED' ? '看完' : status === 'READING' ? '在看' : '未看';
    return status === 'FINISHED' ? '已读' : status === 'READING' ? '在读' : '未读';
  }

  function statusTone(book: ManagementWorkSummary): BadgeTone {
    if (book.statusValue === 'FINISHED') return 'green';
    return book.statusValue === 'READING' ? 'amber' : 'slate';
  }

  function sortableHeader(label: string, sortKey: string, defaultDirection: SortDirection = 'asc') {
    if (!onSort) return label;
    const active = sort === sortKey;
    const nextDirection = active ? (sortDirection === 'asc' ? 'desc' : 'asc') : defaultDirection;
    const directionLabel = sortDirection === 'asc' ? '正序' : '倒序';
    return (
      <button
        type="button"
        onClick={() => onSort(sortKey, nextDirection)}
        aria-pressed={active}
        aria-label={i18nAttribute("{value0}排序{value1}", { value0: label, value1: active ? `，当前${directionLabel}` : '' })}
        className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-2 transition hover:bg-black/[0.045] hover:text-[#4F4944] ${active ? 'bg-[#FFF0EA] text-[#D94724]' : ''}`}
      >
        <span><I18nText>{label}</I18nText></span>
        {active ? (sortDirection === 'asc' ? <ArrowUp size={13} /> : <ArrowDown size={13} />) : <ArrowUpDown size={13} className="opacity-55" />}
      </button>
    );
  }

  return (
    <>
      <div className="space-y-3 md:hidden">
        {books.map((book) => {
          const authorLabel = book.author.trim() && book.author !== '未知作者' ? book.author.trim() : null;

          return (
            <article key={book.id} data-testid="book-list-mobile-card" onContextMenu={(event) => openContextMenu(event, book)} className={`rounded-2xl border bg-white/70 p-4 ${selectedIds.includes(book.id) ? 'border-[#EF4D2F]' : 'border-black/[0.07]'}`}>
              <div className="flex w-full min-w-0 items-start gap-3">
                {selectable ? <input type="checkbox" checked={selectedIds.includes(book.id)} onChange={() => onSelect?.(book)} className="mt-1 h-4 w-4 shrink-0 accent-[#EF4D2F]" aria-label={i18nAttribute(selectedIds.includes(book.id) ? "取消选择《{value0}》" : "选择《{value0}》", { value0: book.title })} /> : null}
                <button type="button" onClick={() => router.push(`/works/${book.id}`)} className="flex min-w-0 flex-1 items-start gap-3 text-left">
                  <Cover book={book} className="h-20 w-14 shrink-0 rounded-md" small />
                  <span className="min-w-0 flex-1">
                    <span data-i18n-skip className="line-clamp-2 font-medium leading-5 text-[#272421]">{book.title}</span>
                    {authorLabel ? <span data-i18n-skip className="mt-1 block truncate text-xs text-[#8A847E]">{authorLabel}</span> : null}
                    <span className="mt-2 flex flex-wrap gap-1.5">
                      <Badge>{mediaLabel(book)}</Badge>
                      <Badge tone={statusTone(book)}>{statusLabel(book)}</Badge>
                      {(book.tags ?? []).slice(0, 1).map((tag) => <Badge key={tag} translate={false}>{tag}</Badge>)}
                    </span>
                  </span>
                </button>
              </div>
              <div className="mt-3 flex justify-end gap-2" data-testid="book-list-mobile-actions">
                <Button variant="ghost" icon={Eye} className="h-11 w-11 min-h-11 px-0 py-0" aria-label={i18nAttribute("查看《{value0}》", { value0: book.title })} title={i18nAttribute("查看")} onClick={() => router.push(`/works/${book.id}`)}><span className="sr-only"><I18nText>查看</I18nText></span></Button>
                {onDelete ? <Button variant="danger" icon={Trash2} className="h-11 w-11 min-h-11 px-0 py-0" aria-label={i18nAttribute("删除《{value0}》", { value0: book.title })} title={i18nAttribute("删除")} onClick={() => onDelete(book)}><span className="sr-only"><I18nText>删除</I18nText></span></Button> : null}
              </div>
            </article>
          );
        })}
      </div>

      <div data-testid="book-list-desktop-table" className="hidden max-w-full overflow-x-auto overscroll-x-contain rounded-2xl border border-black/[0.07] bg-white/70 md:block">
        <table className="w-full min-w-[1200px] table-fixed text-left text-sm">
        <thead className="border-b border-black/[0.06] bg-[#F7F4F0] text-xs font-medium text-[#837D77]">
          <tr>
            {selectable ? <th className="w-12 p-4"><input type="checkbox" checked={allSelected} onChange={(event) => onSelectAll?.(event.target.checked)} className="h-4 w-4 accent-[#EF4D2F]" aria-label={allSelected ? i18nAttribute("取消全选当前页") : i18nAttribute("全选当前页")} /></th> : null}
            <th className="w-[250px] p-2">{sortableHeader('标题', 'title')}</th>
            <th className="w-[86px]">{sortableHeader('作者', 'author')}</th>
            <th className="w-[140px]">{sortableHeader('系列', 'series')}</th>
            <th className="w-[66px]"><I18nText>类型</I18nText></th>
            <th className="w-[118px]"><I18nText>标签</I18nText></th>
            <th className="w-[70px]"><I18nText>状态</I18nText></th>
            <th className="w-[104px]">{sortableHeader('最近阅读', 'recent_read', 'desc')}</th>
            <th className="w-[104px]">{sortableHeader('加入时间', 'recent_import', 'desc')}</th>
            <th className="w-[140px] pr-3 text-right"><I18nText>操作</I18nText></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-black/[0.05]">
          {books.map((book, index) => {
            const authorLabel = book.author.trim() && book.author !== '未知作者' ? book.author.trim() : null;

            return (
              <tr
                key={book.id}
                data-work-id={book.id}
                aria-selected={selectedIds.includes(book.id)}
                onMouseDown={(event) => beginRowSelection(event, book, index)}
                onMouseEnter={() => applyDragSelection(book.id)}
                onContextMenu={(event) => openContextMenu(event, book)}
                className={`cursor-default select-none transition hover:bg-[#FBF6F2] ${selectedIds.includes(book.id) ? 'bg-[#FFF1EB] shadow-[inset_3px_0_0_#EF4D2F]' : ''}`}
              >
                {selectable ? <td className="p-4"><input type="checkbox" checked={selectedIds.includes(book.id)} onChange={() => onSelect?.(book)} className="h-4 w-4 accent-[#EF4D2F]" aria-label={i18nAttribute(selectedIds.includes(book.id) ? "取消选择《{value0}》" : "选择《{value0}》", { value0: book.title })} /></td> : null}
                <td className="overflow-hidden p-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <button type="button" onClick={() => router.push(`/works/${book.id}`)} className="shrink-0 rounded-md outline-none transition hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-[#F6B7A5]" aria-label={i18nAttribute("查看《{value0}》封面", { value0: book.title })}>
                      <Cover book={book} className="h-16 w-11 rounded-md" small />
                    </button>
                    <div className="min-w-0">
                      <button data-i18n-skip type="button" onClick={() => router.push(`/works/${book.id}`)} className="block w-full truncate text-left font-medium text-[#272421] outline-none transition hover:text-[#D94724] hover:underline focus-visible:rounded focus-visible:ring-2 focus-visible:ring-[#F6B7A5]" aria-label={i18nAttribute("查看《{value0}》详情", { value0: book.title })}>{book.title}</button>
                    </div>
                  </div>
                </td>
                <td data-i18n-skip className="truncate px-2 text-[#5F5954]">{authorLabel ?? '—'}</td>
                <td data-i18n-skip className="truncate px-2 text-[#5F5954]" title={book.seriesName?.trim() || undefined}>{book.seriesName?.trim() || '—'}</td>
                <td className="truncate px-2">{mediaLabel(book)}</td>
                <td className="overflow-hidden px-2">
                  <div className="flex gap-1 overflow-hidden">
                    {(book.tags ?? []).slice(0, 2).map((tag) => (
                      <Badge key={tag} translate={false}>{tag}</Badge>
                    ))}
                  </div>
                </td>
                <td className="px-2">
                  <Badge tone={statusTone(book)}>{statusLabel(book)}</Badge>
                </td>
                <td className="truncate px-2 text-[#817B75]">{localDateLabel(book.lastReadAt, '', locale)}</td>
                <td className="truncate px-2 text-[#817B75]">{localDateLabel(book.importedAt, '', locale)}</td>
                <td className="pr-3 text-right">
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" icon={Eye} className="h-9 min-h-9 px-2 py-1.5" aria-label={i18nAttribute("查看《{value0}》", { value0: book.title })} onClick={() => router.push(`/works/${book.id}`)}><span className="hidden 2xl:inline"><I18nText>查看</I18nText></span></Button>
                    {onDelete ? <Button variant="danger" icon={Trash2} className="h-9 min-h-9 px-2 py-1.5" aria-label={i18nAttribute("删除《{value0}》", { value0: book.title })} onClick={() => onDelete(book)}><span className="hidden 2xl:inline"><I18nText>删除</I18nText></span></Button> : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
        </table>
      </div>
    </>
  );
}
