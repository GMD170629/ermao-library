'use client';

import { Eye, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import type { WorkView } from '../../types/work';
import { Badge } from '../ui/badge';
import type { BadgeTone } from '../ui/badge';
import { Button } from '../ui/button';
import { Progress } from '../ui/progress';
import { Cover } from './cover';

export function BookTable({
  books,
  onDelete,
  selectionMode = false,
  selectedIds = [],
  onSelect
}: {
  books: WorkView[];
  onDelete?: (book: WorkView) => void;
  selectionMode?: boolean;
  selectedIds?: string[];
  onSelect?: (book: WorkView) => void;
}) {
  const router = useRouter();

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
            <article key={book.id} data-testid="book-list-mobile-card" className={`rounded-2xl border bg-white/70 p-4 ${selectedIds.includes(book.id) ? 'border-[#EF4D2F]' : 'border-black/[0.07]'}`}>
              <button type="button" onClick={() => selectionMode ? onSelect?.(book) : router.push(`/works/${book.id}`)} className="flex w-full min-w-0 items-start gap-3 text-left">
                {selectionMode ? <input type="checkbox" checked={selectedIds.includes(book.id)} readOnly className="mt-1 accent-[#EF4D2F]" /> : null}
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
              <div className="mt-4 flex items-center gap-3">
                <Progress value={book.progress} className="flex-1" />
                <span className="w-10 text-right text-xs tabular-nums text-[#817B75]">{Math.round(book.progress)}%</span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Button variant="ghost" icon={Eye} className="w-full" onClick={() => router.push(`/works/${book.id}`)}>查看</Button>
                {onDelete && !selectionMode ? <Button variant="danger" icon={Trash2} className="w-full" onClick={() => onDelete(book)}>删除</Button> : null}
              </div>
            </article>
          );
        })}
      </div>

      <div data-testid="book-list-desktop-table" className="hidden overflow-x-auto rounded-2xl border border-black/[0.07] bg-white/70 md:block">
        <table className="w-full min-w-[860px] text-left text-sm">
        <thead className="border-b border-black/[0.06] bg-[#F7F4F0] text-xs font-medium text-[#837D77]">
          <tr>
            {selectionMode ? <th className="w-12 p-4">选择</th> : null}
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
          {books.map((book) => {
            const authorLabel = book.author.trim() && book.author !== '未知作者' ? book.author.trim() : null;

            return (
              <tr key={book.id} className={`transition hover:bg-[#FBF6F2] ${selectedIds.includes(book.id) ? 'bg-[#FFF5F1]' : ''}`}>
                {selectionMode ? <td className="p-4"><input type="checkbox" checked={selectedIds.includes(book.id)} onChange={() => onSelect?.(book)} className="h-4 w-4 accent-[#EF4D2F]" /></td> : null}
                <td className="p-4">
                  <div className="flex items-center gap-3">
                    <Cover book={book} className="h-16 w-11 rounded-md" small />
                    <div>
                      <div className="font-medium text-[#272421]">{book.title}</div>
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
                    {onDelete && !selectionMode ? <Button variant="danger" icon={Trash2} className="min-h-9 px-3 py-2" onClick={() => onDelete(book)}>删除</Button> : null}
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
