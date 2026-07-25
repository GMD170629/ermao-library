'use client';

import Image from 'next/image';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { Cover, type CoverBook } from './cover';

export type BookshelfBook = CoverBook & { id: string };

function shelfRows<T extends BookshelfBook>(books: T[], columns: number) {
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
              : 2;
      setColumns(nextColumns);
    };

    update(element.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => update(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { containerRef, columns };
}

function ShelfBook<T extends BookshelfBook>({
  book,
  onOpen,
  priority = false
}: {
  book: T;
  onOpen: (book: T) => void;
  priority?: boolean;
}) {
  const { t } = useAttributeI18n();

  return (
    <button
      type="button"
      onClick={() => onOpen(book)}
      aria-label={t("查看《{value0}》", { value0: book.title })}
      className="group relative z-20 flex w-full min-w-0 origin-bottom items-end justify-center rounded-md outline-none hover:z-30 focus-visible:z-30 focus-visible:ring-2 focus-visible:ring-[#F6B7A5] focus-visible:ring-offset-4 focus-visible:ring-offset-[#FBFAF8]"
    >
      <span
        data-bookshelf-book-visual
        className="relative block w-full origin-bottom transition-transform duration-200 ease-out group-hover:scale-[1.03] group-focus-visible:scale-[1.03] motion-reduce:transform-none motion-reduce:transition-none"
      >
        <Cover
          book={book}
          size="small"
          priority={priority}
          className="aspect-[2/3] w-full"
          style={{
            borderRadius: '2px',
            transform: 'perspective(900px) rotateY(-0.6deg)',
            transformOrigin: 'bottom center',
            boxShadow: [
              'inset 1px 0 0 rgba(255, 255, 255, 0.28)',
              'inset -1px 0 0 rgba(30, 24, 20, 0.12)',
              '2px 3px 3px -2px rgba(45, 36, 30, 0.25)',
              '7px 10px 14px -10px rgba(45, 36, 30, 0.38)'
            ].join(', ')
          }}
        />
      </span>
    </button>
  );
}

function ShelfBookMetadata<T extends BookshelfBook>({
  book,
  divider = false
}: {
  book: T;
  divider?: boolean;
}) {
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
        title={book.author}
      >
        {book.author}
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

export function BookshelfRail<T extends BookshelfBook>({
  books,
  onOpen,
  testId
}: {
  books: T[];
  onOpen: (book: T) => void;
  testId?: string;
}) {
  return (
    <div data-testid={testId} className="min-w-0">
      <div
        data-testid={testId ? `${testId}-scroller` : undefined}
        className="overflow-x-auto overscroll-x-contain px-1 pb-5 pt-3 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
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

export function BookshelfSection<T extends BookshelfBook>({
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
      <BookshelfRail books={books} onOpen={onOpen} testId={testId} />
    </section>
  );
}

export function BookshelfCollection<T extends BookshelfBook>({
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
            {row.map((book, index) => (
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
