'use client';

import { ArrowLeft, BookOpen, Layers, Search } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { BookCard } from '../../components/book/book-card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { PageTitle } from '../../components/ui/page-title';
import { Select } from '../../components/ui/select';
import type { SeriesSummary, WorkView } from '../../types/work';

type SeriesPayload = {
  ok: boolean;
  data?: { series: SeriesSummary[]; total: number };
  error?: { message: string };
};

type BooksPayload = {
  ok: boolean;
  data?: { books: WorkView[]; total: number; page: number; pageSize: number; totalPages: number };
  error?: { message: string };
};

async function readApiJson<T>(response: Response, fallbackMessage: string): Promise<T> {
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(response.ok ? fallbackMessage : `${fallbackMessage}（HTTP ${response.status}）`);
    }
  }
  if (!response.ok) {
    const message = typeof payload === 'object' && payload && 'error' in payload
      ? (payload as { error?: { message?: string } }).error?.message
      : null;
    throw new Error(message || `${fallbackMessage}（HTTP ${response.status}）`);
  }
  return payload as T;
}

const sortOptions = [
  { value: 'series_index', label: '卷号' },
  { value: 'title', label: '标题' },
  { value: 'updated', label: '最近更新' }
];

export function SeriesPage({ initialName = '' }: { initialName?: string }) {
  const router = useRouter();
  const [seriesName, setSeriesName] = useState(initialName.trim());
  const [series, setSeries] = useState<SeriesSummary[]>([]);
  const [seriesTotal, setSeriesTotal] = useState(0);
  const [books, setBooks] = useState<WorkView[]>([]);
  const [bookTotal, setBookTotal] = useState(0);
  const [sort, setSort] = useState('series_index');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setSeriesName(initialName.trim());
    setSearch('');
    window.dispatchEvent(new Event('shuku:series-route-change'));
  }, [initialName]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');

    if (!seriesName) {
      fetch('/api/series?visibility=active&limit=100')
        .then((response) => readApiJson<SeriesPayload>(response, '读取系列失败'))
        .then((payload) => {
          if (!active) return;
          if (!payload.ok) throw new Error(payload.error?.message ?? '读取系列失败');
          setSeries(payload.data?.series ?? []);
          setSeriesTotal(payload.data?.total ?? 0);
          setBooks([]);
          setBookTotal(0);
        })
        .catch((reason) => {
          if (active) setError(reason instanceof Error ? reason.message : '读取系列失败');
        })
        .finally(() => {
          if (active) setLoading(false);
        });
      return () => {
        active = false;
      };
    }

    const params = new URLSearchParams({
      visibility: 'active',
      pageSize: '60',
      seriesName,
      sort
    });
    fetch(`/api/works?${params}`)
      .then((response) => readApiJson<BooksPayload>(response, '读取系列图书失败'))
      .then((payload) => {
        if (!active) return;
        if (!payload.ok) throw new Error(payload.error?.message ?? '读取系列图书失败');
        setBooks(payload.data?.books ?? []);
        setBookTotal(payload.data?.total ?? 0);
        setSeries([]);
        setSeriesTotal(0);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : '读取系列图书失败');
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [seriesName, sort]);

  const filteredSeries = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return series;
    return series.filter((item) => item.name.toLowerCase().includes(keyword));
  }, [search, series]);

  if (seriesName) {
    return (
      <div className="space-y-6">
        <PageTitle
          title={seriesName}
          desc={`系列详情 · ${bookTotal} 本在库读物`}
          action={
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" icon={ArrowLeft} onClick={() => router.push('/series')}>全部系列</Button>
              <Select value={sort} options={sortOptions} onChange={setSort} ariaLabel="系列排序" />
            </div>
          }
        />
        {loading ? <div className="shuku-loading-panel p-8 text-sm" role="status" aria-live="polite">正在读取系列图书...</div> : null}
        {error ? <div className="rounded-3xl border border-red-100 bg-red-50 p-8 text-sm text-red-700">{error}</div> : null}
        {!loading && !error && books.length === 0 ? (
          <div className="rounded-3xl border border-slate-200 bg-white p-8">
            <div className="flex items-center gap-3 text-slate-900">
              <Layers size={20} />
              <div className="font-semibold">这个系列暂无在库读物</div>
            </div>
            <p className="mt-2 text-sm text-slate-500">该系列可能还没有图书，或相关读物已被隐藏。</p>
          </div>
        ) : null}
        {!loading && !error && books.length > 0 ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,170px))] justify-start gap-4">
            {books.map((book) => (
              <BookCard key={book.id} book={book} onClick={() => router.push(`/works/${book.id}`)} />
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageTitle title="系列" desc={`当前书库中的图书系列 · ${seriesTotal} 个`} />
      <div className="rounded-[22px] border border-slate-200 bg-white p-3 shadow-sm">
        <div className="flex h-10 min-w-0 items-center gap-3 rounded-2xl border border-slate-200 px-3 md:max-w-md">
          <Search size={16} className="text-slate-400" />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索系列" className="w-full bg-transparent text-sm outline-none" />
        </div>
      </div>
      {loading ? <div className="shuku-loading-panel p-8 text-sm" role="status" aria-live="polite">正在读取系列...</div> : null}
      {error ? <div className="rounded-3xl border border-red-100 bg-red-50 p-8 text-sm text-red-700">{error}</div> : null}
      {!loading && !error && filteredSeries.length === 0 ? (
        <div className="rounded-3xl border border-slate-200 bg-white p-8 text-sm text-slate-500">暂无系列。为图书补充系列元数据后，这里会自动出现。</div>
      ) : null}
      {!loading && !error && filteredSeries.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filteredSeries.map((item) => (
            <Link
              key={item.name}
              href={`/series?name=${encodeURIComponent(item.name)}`}
              className={cn('rounded-[22px] border border-slate-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md')}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="line-clamp-2 font-semibold text-slate-950">{item.name}</div>
                  <div className="mt-2 flex items-center gap-2 text-sm text-slate-500">
                    <BookOpen size={15} />
                    {item.bookCount} 本读物
                  </div>
                </div>
                <Badge tone="blue">系列</Badge>
              </div>
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  );
}
