'use client';

import { Check, Trash2 } from 'lucide-react';
import type { KeyboardEvent, MouseEvent } from 'react';
import { Progress } from '../ui/progress';
import { Cover } from './cover';
import type { CoverBook } from './cover';

type CardMediaKind = 'EBOOK' | 'COMIC' | 'AUDIOBOOK';

const mediaLabels: Record<CardMediaKind, string> = {
  EBOOK: '电子书',
  COMIC: '漫画',
  AUDIOBOOK: '有声书'
};

function consumptionStatusLabel(status: string | undefined, mediaKinds: CardMediaKind[]) {
  const normalized = status === 'FINISHED' ? 'FINISHED' : status === 'READING' ? 'READING' : 'UNREAD';
  if (mediaKinds.length !== 1) return normalized === 'FINISHED' ? '已完成' : normalized === 'READING' ? '进行中' : '未开始';
  if (mediaKinds[0] === 'AUDIOBOOK') return normalized === 'FINISHED' ? '听完' : normalized === 'READING' ? '在听' : '未听';
  if (mediaKinds[0] === 'COMIC') return normalized === 'FINISHED' ? '看完' : normalized === 'READING' ? '在看' : '未看';
  return normalized === 'FINISHED' ? '已读' : normalized === 'READING' ? '在读' : '未读';
}

export function BookCard({
  book,
  compact = false,
  priority = false,
  onDelete,
  onClick,
  selectable = false,
  selected = false,
  onSelect
}: {
  book: CoverBook & {
    tags: string[];
    progress: number;
    type: string;
    format: string;
    status?: string;
    statusValue?: string;
    totalUnits?: number;
    versionCount?: number;
    volumeCount?: number;
    primaryEditionName?: string | null;
    availableMediaKinds?: CardMediaKind[];
  };
  compact?: boolean;
  priority?: boolean;
  onDelete?: () => void;
  onClick?: () => void;
  selectable?: boolean;
  selected?: boolean;
  onSelect?: () => void;
}) {
  const authorLabel = book.author.trim() && book.author !== '未知作者' ? book.author.trim() : null;
  const hasProgress = book.progress > 0 && book.progress < 100;
  const mediaKinds = book.availableMediaKinds?.length
    ? book.availableMediaKinds
    : [book.type === 'comic' ? 'COMIC' : book.type === 'audiobook' ? 'AUDIOBOOK' : 'EBOOK'] as CardMediaKind[];
  const readingLabel = consumptionStatusLabel(book.statusValue, mediaKinds);

  function deleteBook(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    onDelete?.();
  }

  function openBook(event: KeyboardEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget || !onClick || (event.key !== 'Enter' && event.key !== ' ')) return;
    event.preventDefault();
    onClick();
  }

  return (
    <div
      onClick={onClick}
      onKeyDown={openBook}
      role={onClick ? 'link' : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-label={onClick ? `查看《${book.title}》` : undefined}
      className={`group relative min-w-0 cursor-pointer rounded-xl outline-none transition focus-visible:ring-2 focus-visible:ring-[#F6B7A5] ${selected ? 'ring-2 ring-[#EF4D2F] ring-offset-4 ring-offset-[#F7F4F0]' : ''}`}
    >
      {selectable ? (
        <label className={`absolute left-2 top-2 z-10 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full border shadow-sm ${selected ? 'border-[#EF4D2F] bg-[#EF4D2F] text-white' : 'border-black/[0.12] bg-white/95 text-transparent'}`} onClick={(event) => event.stopPropagation()}>
          <input type="checkbox" checked={selected} onChange={onSelect} className="sr-only" aria-label={`${selected ? '取消选择' : '选择'}《${book.title}》`} />
          <Check size={15} aria-hidden="true" />
        </label>
      ) : null}
      {onDelete ? (
        <button
          type="button"
          onClick={deleteBook}
          className="absolute right-2 top-2 z-10 flex h-8 w-8 items-center justify-center rounded-full border border-black/[0.06] bg-white/95 text-red-600 opacity-0 shadow-sm transition hover:bg-red-50 focus:opacity-100 group-hover:opacity-100"
          title="删除记录"
          aria-label={`删除 ${book.title}`}
        >
          <Trash2 size={15} />
        </button>
      ) : null}
      <Cover
        book={book}
        size={compact ? 'small' : 'medium'}
        priority={priority}
        className="aspect-[2/3] w-full rounded-[9px] transition duration-200 group-hover:-translate-y-0.5"
      />
      <div className="mt-2">
        <div className={compact ? 'line-clamp-1 text-[13px] font-medium text-[#24211F]' : 'line-clamp-1 text-sm font-medium text-[#24211F]'}>{book.title}</div>
        {authorLabel ? <div className="mt-0.5 line-clamp-1 text-xs text-[#89837D]">{authorLabel}</div> : null}
        <div className="mt-1 line-clamp-1 text-[11px] text-[#9A948E]">{mediaKinds.map((kind) => mediaLabels[kind]).join(' · ')}</div>
        {hasProgress ? (
          <div className="mt-1.5 flex items-center gap-2">
            <Progress value={book.progress} className="h-1 flex-1 bg-[#E4E0DC]" />
            <span className="shrink-0 text-[11px] tabular-nums text-[#77716B]">{Math.round(book.progress)}%</span>
          </div>
        ) : readingLabel ? (
          <div className="mt-1 text-xs text-[#8B857F]">{readingLabel}</div>
        ) : null}
      </div>
    </div>
  );
}
