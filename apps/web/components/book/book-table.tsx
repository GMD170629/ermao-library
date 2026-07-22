'use client';

import { Eye, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { useEffect, useRef } from 'react';
import type { WorkView } from '../../types/work';
import { Badge } from '../ui/badge';
import type { BadgeTone } from '../ui/badge';
import { Button } from '../ui/button';
import { Progress } from '../ui/progress';
import { Cover } from './cover';

export function BookTable({
  books,
  onDelete,
  selectable = false,
  selectedIds = [],
  onSelect,
  onSelectAll,
  onSelectionChange,
  onContextMenu
}: {
  books: WorkView[];
  onDelete?: (book: WorkView) => void;
  selectable?: boolean;
  selectedIds?: string[];
  onSelect?: (book: WorkView) => void;
  onSelectAll?: (selected: boolean) => void;
  onSelectionChange?: (ids: string[]) => void;
  onContextMenu?: (book: WorkView, position: { x: number; y: number }) => void;
}) {
  const router = useRouter();
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

  function beginRowSelection(event: ReactMouseEvent<HTMLTableRowElement>, book: WorkView, index: number) {
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

  function openContextMenu(event: ReactMouseEvent<HTMLElement>, book: WorkView) {
    if (!selectable || !onContextMenu) return;
    event.preventDefault();
    if (!selectedRef.current.has(book.id)) commitSelection(new Set([book.id]));
    onContextMenu(book, { x: event.clientX, y: event.clientY });
  }

  function mediaLabel(book: WorkView) {
    const kinds = book.availableMediaKinds?.length
      ? book.availableMediaKinds
      : [book.type === 'comic' ? 'COMIC' : book.type === 'audiobook' ? 'AUDIOBOOK' : 'EBOOK'];
    return kinds.map((kind) => kind === 'AUDIOBOOK' ? '有声书' : kind === 'COMIC' ? '漫画' : '电子书').join(' · ');
  }

  function statusLabel(book: WorkView) {
    const kinds = book.availableMediaKinds?.length
      ? book.availableMediaKinds
      : [book.type === 'comic' ? 'COMIC' : book.type === 'audiobook' ? 'AUDIOBOOK' : 'EBOOK'];
    const status = book.statusValue;
    if (kinds.length !== 1) return status === 'FINISHED' ? '已完成' : status === 'READING' ? '进行中' : '未开始';
    if (kinds[0] === 'AUDIOBOOK') return status === 'FINISHED' ? '听完' : status === 'READING' ? '在听' : '未听';
    if (kinds[0] === 'COMIC') return status === 'FINISHED' ? '看完' : status === 'READING' ? '在看' : '未看';
    return status === 'FINISHED' ? '已读' : status === 'READING' ? '在读' : '未读';
  }

  function statusTone(book: WorkView): BadgeTone {
    return book.statusValue === 'FINISHED' ? 'green' : book.statusValue === 'READING' ? 'amber' : 'slate';
  }

  return (
    <>
      <div className="space-y-3 md:hidden">
        {books.map((book) => {
          const authorLabel = book.author.trim() && book.author !== '未知作者' ? book.author.trim() : null;

          return (
            <article key={book.id} data-testid="book-list-mobile-card" onContextMenu={(event) => openContextMenu(event, book)} className={`rounded-2xl border bg-white/70 p-4 ${selectedIds.includes(book.id) ? 'border-[#EF4D2F]' : 'border-black/[0.07]'}`}>
              <div className="flex w-full min-w-0 items-start gap-3">
                {selectable ? <input type="checkbox" checked={selectedIds.includes(book.id)} onChange={() => onSelect?.(book)} className="mt-1 h-4 w-4 shrink-0 accent-[#EF4D2F]" aria-label={`${selectedIds.includes(book.id) ? '取消选择' : '选择'}《${book.title}》`} /> : null}
                <button type="button" onClick={() => router.push(`/works/${book.id}`)} className="flex min-w-0 flex-1 items-start gap-3 text-left">
                  <Cover book={book} className="h-20 w-14 shrink-0 rounded-md" small />
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 font-medium leading-5 text-[#272421]">{book.title}</span>
                    {authorLabel ? <span className="mt-1 block truncate text-xs text-[#8A847E]">{authorLabel}</span> : null}
                    <span className="mt-2 flex flex-wrap gap-1.5">
                      <Badge>{mediaLabel(book)}</Badge>
                      <Badge tone={statusTone(book)}>{statusLabel(book)}</Badge>
                      {book.tags.slice(0, 1).map((tag) => <Badge key={tag}>{tag}</Badge>)}
                    </span>
                  </span>
                </button>
              </div>
              <div className="mt-4 flex items-center gap-3">
                <Progress value={book.progress} className="flex-1" />
                <span className="w-10 text-right text-xs tabular-nums text-[#817B75]">{Math.round(book.progress)}%</span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Button variant="ghost" icon={Eye} className="w-full" onClick={() => router.push(`/works/${book.id}`)}>查看</Button>
                {onDelete ? <Button variant="danger" icon={Trash2} className="w-full" onClick={() => onDelete(book)}>删除</Button> : null}
              </div>
            </article>
          );
        })}
      </div>

      <div data-testid="book-list-desktop-table" className="hidden overflow-x-auto rounded-2xl border border-black/[0.07] bg-white/70 md:block">
        <table className="w-full min-w-[860px] text-left text-sm">
        <thead className="border-b border-black/[0.06] bg-[#F7F4F0] text-xs font-medium text-[#837D77]">
          <tr>
            {selectable ? <th className="w-12 p-4"><input type="checkbox" checked={allSelected} onChange={(event) => onSelectAll?.(event.target.checked)} className="h-4 w-4 accent-[#EF4D2F]" aria-label={allSelected ? '取消全选当前页' : '全选当前页'} /></th> : null}
            <th className="p-4">读物</th>
            <th>类型</th>
            <th>标签</th>
            <th>状态</th>
            <th>进度</th>
            <th>最近阅读</th>
            <th className="pr-4 text-right">操作</th>
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
                {selectable ? <td className="p-4"><input type="checkbox" checked={selectedIds.includes(book.id)} onChange={() => onSelect?.(book)} className="h-4 w-4 accent-[#EF4D2F]" aria-label={`${selectedIds.includes(book.id) ? '取消选择' : '选择'}《${book.title}》`} /></td> : null}
                <td className="p-4">
                  <div className="flex items-center gap-3">
                    <button type="button" onClick={() => router.push(`/works/${book.id}`)} className="shrink-0 rounded-md outline-none transition hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-[#F6B7A5]" aria-label={`查看《${book.title}》封面`}>
                      <Cover book={book} className="h-16 w-11 rounded-md" small />
                    </button>
                    <div className="min-w-0">
                      <button type="button" onClick={() => router.push(`/works/${book.id}`)} className="max-w-md truncate text-left font-medium text-[#272421] outline-none transition hover:text-[#D94724] hover:underline focus-visible:rounded focus-visible:ring-2 focus-visible:ring-[#F6B7A5]" aria-label={`查看《${book.title}》详情`}>{book.title}</button>
                      {authorLabel ? <div className="mt-1 max-w-md truncate text-xs text-[#8A847E]">{authorLabel}</div> : null}
                    </div>
                  </div>
                </td>
                <td>{mediaLabel(book)}</td>
                <td>
                  <div className="flex gap-1">
                    {book.tags.slice(0, 2).map((tag) => (
                      <Badge key={tag}>{tag}</Badge>
                    ))}
                  </div>
                </td>
                <td>
                  <Badge tone={statusTone(book)}>{statusLabel(book)}</Badge>
                </td>
                <td className="w-40">
                  <Progress value={book.progress} />
                </td>
                <td className="text-[#817B75]">{book.lastRead}</td>
                <td className="pr-4 text-right">
                  <div className="flex justify-end gap-2">
                    <Button variant="ghost" icon={Eye} className="min-h-9 px-3 py-2" onClick={() => router.push(`/works/${book.id}`)}>查看</Button>
                    {onDelete ? <Button variant="danger" icon={Trash2} className="min-h-9 px-3 py-2" onClick={() => onDelete(book)}>删除</Button> : null}
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
