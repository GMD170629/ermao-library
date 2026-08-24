'use client';

import Image from 'next/image';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode
} from 'react';
import { I18nText, useI18n as useAttributeI18n } from '@/i18n/provider';
import { Cover, type CoverBook } from './cover';
import { CoverReadingProgress, coverReadingProgressState } from './cover-reading-progress';
import type { ResourceImportSummary } from '../../types/book';

export type BookshelfItem = CoverBook & { id: string; progress: number; resourceImportSummary?: ResourceImportSummary };

function shelfRows<T extends BookshelfItem>(books: T[], columns: number) {
  const rows: T[][] = [];
  for (let index = 0; index < books.length; index += columns) {
    rows.push(books.slice(index, index + columns));
  }
  return rows;
}

function useBookshelfColumns() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [columns, setColumns] = useState(10);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const update = (width: number) => {
      const nextColumns = width >= 1160
        ? 10
        : width >= 940
          ? 8
          : width >= 720
            ? 6
            : width >= 500
              ? 4
              : 3;
      setColumns(nextColumns);
    };

    update(element.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => update(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { containerRef, columns };
}

const HORIZONTAL_DRAG_THRESHOLD_PX = 4;

function useHorizontalDragScroll() {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    scrollLeft: number;
    moved: boolean;
  } | null>(null);
  const clickSuppressionTimerRef = useRef<number | null>(null);
  const suppressClickRef = useRef(false);
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => () => {
    if (clickSuppressionTimerRef.current !== null) {
      window.clearTimeout(clickSuppressionTimerRef.current);
    }
  }, []);

  useEffect(() => {
    window.addEventListener('pointermove', onWindowPointerMove, { passive: false });
    window.addEventListener('pointerup', finishPointerDrag);
    window.addEventListener('pointercancel', finishPointerDrag);
    return () => {
      window.removeEventListener('pointermove', onWindowPointerMove);
      window.removeEventListener('pointerup', finishPointerDrag);
      window.removeEventListener('pointercancel', finishPointerDrag);
    };
  }, []);

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType === 'touch' || !event.isPrimary || event.button !== 0) return;
    const scroller = scrollerRef.current;
    if (!scroller) return;

    if (clickSuppressionTimerRef.current !== null) {
      window.clearTimeout(clickSuppressionTimerRef.current);
      clickSuppressionTimerRef.current = null;
    }
    suppressClickRef.current = false;
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: scroller.scrollLeft,
      moved: false
    };
  }

  function onWindowPointerMove(event: PointerEvent) {
    const drag = dragRef.current;
    const scroller = scrollerRef.current;
    if (!drag || !scroller || drag.pointerId !== event.pointerId) return;

    const horizontalDistance = event.clientX - drag.startX;
    const verticalDistance = event.clientY - drag.startY;
    if (!drag.moved) {
      if (Math.abs(verticalDistance) > HORIZONTAL_DRAG_THRESHOLD_PX && Math.abs(verticalDistance) > Math.abs(horizontalDistance)) {
        dragRef.current = null;
        return;
      }
      if (Math.abs(horizontalDistance) <= HORIZONTAL_DRAG_THRESHOLD_PX) return;

      drag.moved = true;
      setIsDragging(true);
    }

    event.preventDefault();
    scroller.scrollLeft = drag.scrollLeft - horizontalDistance;
  }

  function finishPointerDrag(event: PointerEvent) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    dragRef.current = null;
    if (drag.moved) {
      suppressClickRef.current = true;
      clickSuppressionTimerRef.current = window.setTimeout(() => {
        suppressClickRef.current = false;
        clickSuppressionTimerRef.current = null;
      }, 0);
    }
    setIsDragging(false);
  }

  function onClickCapture(event: ReactMouseEvent<HTMLDivElement>) {
    if (!suppressClickRef.current) return;
    event.preventDefault();
    event.stopPropagation();
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.currentTarget !== event.target) return;
    const scroller = scrollerRef.current;
    if (!scroller || scroller.scrollWidth <= scroller.clientWidth) return;

    if (event.key === 'Home') {
      event.preventDefault();
      scroller.scrollLeft = 0;
      return;
    }
    if (event.key === 'End') {
      event.preventDefault();
      scroller.scrollLeft = scroller.scrollWidth;
      return;
    }
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;

    event.preventDefault();
    const distance = Math.max(240, scroller.clientWidth * 0.75);
    scroller.scrollBy({ left: event.key === 'ArrowLeft' ? -distance : distance });
  }

  return {
    scrollerRef,
    isDragging,
    onPointerDown,
    onClickCapture,
    onKeyDown
  };
}

function ShelfBook<T extends BookshelfItem>({
  book,
  onOpen,
  priority = false
}: {
  book: T;
  onOpen: (book: T) => void;
  priority?: boolean;
}) {
  const { t } = useAttributeI18n();
  const progress = coverReadingProgressState(book.progress);

  return (
    <button
      type="button"
      onClick={() => onOpen(book)}
      onDragStart={(event) => event.preventDefault()}
      aria-label={progress.visible
        ? t("查看《{value0}》，阅读进度 {value1}%", {
            value0: book.title,
            value1: String(progress.roundedValue)
          })
        : t("查看《{value0}》", { value0: book.title })}
      className="group relative z-20 flex w-full min-w-0 origin-bottom items-end justify-center rounded-md outline-none hover:z-30 focus-visible:z-30 focus-visible:ring-2 focus-visible:ring-[#F6B7A5] focus-visible:ring-offset-4 focus-visible:ring-offset-[#FBFAF8]"
    >
      <span
        data-bookshelf-book-visual
        className="relative mx-auto flex w-full max-w-full origin-bottom items-end justify-center [container-type:inline-size] transition-transform duration-200 ease-out group-hover:scale-[1.03] group-focus-visible:scale-[1.03] motion-reduce:transform-none motion-reduce:transition-none"
      >
        <Cover
          book={book}
          size="small"
          variant="bookshelf"
          priority={priority}
          style={{
            borderRadius: '2px',
            transform: 'perspective(900px) rotateY(-0.6deg)',
            transformOrigin: 'bottom center',
            boxShadow: [
              '2px 3px 3px -2px rgba(45, 36, 30, 0.25)',
              '7px 10px 14px -10px rgba(45, 36, 30, 0.38)'
            ].join(', ')
          }}
        />
        <CoverReadingProgress progress={book.progress} surface="bookshelf" />
        {book.resourceImportSummary?.pending ? <span className="absolute inset-x-1 bottom-1 rounded bg-amber-950/80 px-1 py-0.5 text-center text-[10px] font-medium text-white"><I18nText>导入中</I18nText></span> : null}
      </span>
    </button>
  );
}

function ShelfBookMetadata<T extends BookshelfItem>({
  book,
  divider = false
}: {
  book: T;
  divider?: boolean;
}) {
  const { t } = useAttributeI18n();
  const author = book.author?.trim() || t("未知作者");

  return (
    <div
      data-bookshelf-book-metadata
      data-i18n-skip
      className={`min-w-0 px-2.5 py-2.5 text-left sm:px-3 ${divider ? 'border-r border-[#DED7CF]/70' : ''}`}
    >
      <div
        className="truncate text-[12px] font-medium leading-5 text-[#302C29] sm:text-[13px]"
        title={book.title}
      >
        {book.title}
      </div>
      <div
        className="mt-0.5 truncate text-[11px] leading-4 text-[#817A74] sm:text-[12px]"
        title={author}
      >
        {author}
      </div>
    </div>
  );
}

function ShelfLedge() {
  return (
    <div
      data-testid="bookshelf-ledge"
      className="relative z-10 -mt-[3px] h-[30px]"
      aria-hidden="true"
    >
      <div
        data-testid="bookshelf-ledge-asset"
        className="flex h-[14px] w-full items-stretch"
        style={{
          filter: 'drop-shadow(0 7px 5px rgba(50, 38, 30, 0.28))'
        }}
      >
        <Image
          src="/images/bookshelf-ledge-left-v2.png"
          alt=""
          width={80}
          height={57}
          unoptimized
          priority
          className="h-[14px] w-5 shrink-0 object-fill"
        />
        <Image
          src="/images/bookshelf-ledge-center-v2.png"
          alt=""
          width={128}
          height={57}
          unoptimized
          priority
          className="h-[14px] min-w-0 flex-1 object-fill"
        />
        <Image
          src="/images/bookshelf-ledge-right-v2.png"
          alt=""
          width={80}
          height={57}
          unoptimized
          priority
          className="h-[14px] w-5 shrink-0 object-fill"
        />
      </div>
    </div>
  );
}

export function BookshelfRail<T extends BookshelfItem>({
  books,
  onOpen,
  testId,
  ariaLabel
}: {
  books: T[];
  onOpen: (book: T) => void;
  testId?: string;
  ariaLabel?: string;
}) {
  const dragScroll = useHorizontalDragScroll();

  return (
    <div data-testid={testId} className="min-w-0">
      <div
        ref={dragScroll.scrollerRef}
        data-testid={testId ? `${testId}-scroller` : undefined}
        role={ariaLabel ? 'region' : undefined}
        aria-label={ariaLabel}
        tabIndex={0}
        onPointerDown={dragScroll.onPointerDown}
        onClickCapture={dragScroll.onClickCapture}
        onKeyDown={dragScroll.onKeyDown}
        className={`overflow-x-auto overscroll-x-contain px-1 pb-5 pt-3 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${dragScroll.isDragging ? 'cursor-grabbing select-none' : 'cursor-grab'}`}
      >
        <div className="min-w-max">
          <div className="flex items-end gap-5 px-5 sm:gap-6 sm:px-7">
            {books.map((book, index) => (
              <div key={book.id} className="w-[104px] shrink-0 sm:w-[118px] xl:w-[128px]">
                <ShelfBook book={book} onOpen={onOpen} priority={index === 0} />
              </div>
            ))}
          </div>
          <ShelfLedge />
          <div
            data-testid={testId ? `${testId}-metadata` : undefined}
            className="-mt-4 flex gap-5 border-b border-[#D8D0C7]/80 bg-[#F7F2EA] px-5 shadow-[0_5px_10px_-10px_rgba(45,36,30,0.5)] sm:gap-6 sm:px-7"
          >
            {books.map((book, index) => (
              <div key={book.id} className="w-[104px] shrink-0 sm:w-[118px] xl:w-[128px]">
                <ShelfBookMetadata book={book} divider={index < books.length - 1} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function BookshelfSection<T extends BookshelfItem>({
  title,
  books,
  onOpen,
  action,
  testId
}: {
  title: string;
  books: T[];
  onOpen: (book: T) => void;
  action?: ReactNode;
  testId?: string;
}) {
  return (
    <section className="mt-7">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-[22px] font-semibold tracking-tight text-[#24211F]">{title}</h2>
        {action}
      </div>
      <BookshelfRail books={books} onOpen={onOpen} testId={testId} ariaLabel={title} />
    </section>
  );
}

export function BookshelfCollection<T extends BookshelfItem>({
  books,
  onOpen,
  testId
}: {
  books: T[];
  onOpen: (book: T) => void;
  testId?: string;
}) {
  const { containerRef, columns } = useBookshelfColumns();
  const rows = useMemo(() => shelfRows(books, columns), [books, columns]);

  return (
    <div ref={containerRef} data-testid={testId} className="space-y-10">
      {rows.map((row, rowIndex) => (
        <div key={`${row[0]?.id ?? 'empty'}-${rowIndex}`} data-testid="bookshelf-row" className="min-w-0 pt-2">
          <div
            className="grid items-end gap-4 px-5 sm:gap-5 sm:px-7"
            style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
          >
            {row.map((book) => (
              <ShelfBook
                key={book.id}
                book={book}
                onOpen={onOpen}
                priority={rowIndex === 0}
              />
            ))}
          </div>
          <ShelfLedge />
          <div
            data-testid="bookshelf-metadata-band"
            className="-mt-4 grid border-b border-[#D8D0C7]/80 bg-[#F7F2EA] px-5 shadow-[0_5px_10px_-10px_rgba(45,36,30,0.5)] sm:px-7"
            style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
          >
            {row.map((book, index) => (
              <ShelfBookMetadata key={book.id} book={book} divider={index < row.length - 1} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
