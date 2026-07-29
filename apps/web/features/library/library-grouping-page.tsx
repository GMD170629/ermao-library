'use client';

import { BookOpen, LibraryBig, Loader2, Search, UsersRound } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { MobileNavigationTrigger } from '../../components/layout/mobile-navigation';
import { Button } from '../../components/ui/button';
import { I18nText, useI18n } from '@/i18n/provider';
import {
  fetchLibraryGroupings,
  type LibraryGrouping,
  type LibraryGroupingKind
} from './api/groupings';

const PAGE_SIZE = 48;

const pageCopy = {
  SERIES: {
    title: '系列',
    description: '按丛书系列浏览书库中的图书。',
    searchPlaceholder: '搜索系列',
    emptyTitle: '暂无系列',
    emptyDescription: '带有丛书系列信息的图书会显示在这里。',
    icon: LibraryBig
  },
  AUTHOR: {
    title: '作者',
    description: '按作者浏览书库中的图书。',
    searchPlaceholder: '搜索作者',
    emptyTitle: '暂无作者',
    emptyDescription: '带有作者信息的图书会显示在这里。',
    icon: UsersRound
  }
} satisfies Record<LibraryGroupingKind, {
  title: string;
  description: string;
  searchPlaceholder: string;
  emptyTitle: string;
  emptyDescription: string;
  icon: typeof LibraryBig;
}>;

export function LibraryGroupingPage({ kind }: { kind: LibraryGroupingKind }) {
  const router = useRouter();
  const { t, formatNumber } = useI18n();
  const copy = pageCopy[kind];
  const PageIcon = copy.icon;
  const [search, setSearch] = useState('');
  const [groups, setGroups] = useState<LibraryGrouping[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const normalizedSearch = useMemo(() => search.trim(), [search]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError('');
      fetchLibraryGroupings({
        kind,
        page: 1,
        pageSize: PAGE_SIZE,
        search: normalizedSearch,
        signal: controller.signal
      })
        .then((result) => {
          setGroups(result.groups);
          setPage(result.page);
          setTotal(result.total);
          setTotalPages(result.totalPages);
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setError(reason instanceof Error ? reason.message : t('读取书库分组失败'));
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [kind, normalizedSearch, t]);

  async function loadMore() {
    if (loadingMore || page >= totalPages) return;
    setLoadingMore(true);
    setError('');
    try {
      const result = await fetchLibraryGroupings({
        kind,
        page: page + 1,
        pageSize: PAGE_SIZE,
        search: normalizedSearch
      });
      setGroups((current) => [...current, ...result.groups]);
      setPage(result.page);
      setTotal(result.total);
      setTotalPages(result.totalPages);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('读取书库分组失败'));
    } finally {
      setLoadingMore(false);
    }
  }

  function openGroup(group: LibraryGrouping) {
    const params = new URLSearchParams({
      facetKind: kind,
      facetId: group.id,
      facetName: group.name
    });
    if (kind === 'SERIES') {
      params.set('sort', 'series_index');
      params.set('sortDirection', 'asc');
    }
    router.push(`/library?${params}`);
  }

  return (
    <div className="mx-auto max-w-[1280px]">
      <header className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3 sm:gap-4">
          <MobileNavigationTrigger />
          <div>
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-[14px] bg-[#F9DED4] text-[#E94B2D]">
                <PageIcon size={23} strokeWidth={1.65} aria-hidden="true" />
              </span>
              <h1 className="text-[30px] font-semibold leading-none tracking-[-0.035em] text-[#1E1D1B] sm:text-[44px]">
                {t(copy.title)}
              </h1>
              {!loading ? <span className="text-[13px] text-[#8A847E] sm:text-[15px]">{formatNumber(total)} <I18nText>个分组</I18nText></span> : null}
            </div>
            <p className="mt-4 text-sm leading-6 text-[#817B75] sm:text-base">{t(copy.description)}</p>
          </div>
        </div>
      </header>

      <label className="mt-8 flex h-12 w-full items-center gap-3 rounded-xl border border-black/[0.09] bg-white px-4 sm:max-w-[380px]">
        <Search size={18} className="shrink-0 text-[#8A847E]" strokeWidth={1.8} aria-hidden="true" />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t(copy.searchPlaceholder)}
          aria-label={t(copy.searchPlaceholder)}
          className="min-w-0 flex-1 bg-transparent text-sm text-[#2A2724] outline-none placeholder:text-[#98928C]"
        />
      </label>

      {loading ? (
        <div className="mt-8 flex min-h-[240px] items-center justify-center rounded-2xl bg-black/[0.02] text-sm text-[#817B75]" role="status">
          <Loader2 size={17} className="mr-2 animate-spin" />
          <I18nText>正在读取分组...</I18nText>
        </div>
      ) : null}

      {error ? <div className="mt-6 rounded-2xl bg-red-50 px-6 py-5 text-sm text-red-700" role="alert">{error}</div> : null}

      {!loading && !error && groups.length === 0 ? (
        <div className="mt-8 flex min-h-[260px] flex-col items-center justify-center rounded-[24px] border border-dashed border-black/[0.1] bg-black/[0.018] px-8 text-center">
          <PageIcon size={34} strokeWidth={1.45} className="text-[#A49C95]" aria-hidden="true" />
          <h2 className="mt-4 text-lg font-semibold text-[#3A3632]">{t(copy.emptyTitle)}</h2>
          <p className="mt-2 text-sm leading-6 text-[#817B75]">{t(copy.emptyDescription)}</p>
        </div>
      ) : null}

      {!loading && groups.length > 0 ? (
        <>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {groups.map((group) => (
              <button
                key={group.id}
                type="button"
                onClick={() => openGroup(group)}
                aria-label={t('打开“{value0}”，共 {value1} 本图书', {
                  value0: group.name,
                  value1: formatNumber(group.bookCount)
                })}
                className="group flex min-h-32 flex-col justify-between rounded-[20px] border border-[#E5DED8] bg-white p-5 text-left outline-none transition duration-200 hover:-translate-y-0.5 hover:border-[#E9B7A7] hover:shadow-[0_12px_28px_rgba(73,52,43,0.08)] focus-visible:ring-4 focus-visible:ring-[#FBE1D9]"
              >
                <div className="flex items-start justify-between gap-4">
                  <span data-i18n-skip className="line-clamp-2 font-semibold leading-6 text-[#2A2825]">{group.name}</span>
                  <PageIcon size={20} strokeWidth={1.55} className="shrink-0 text-[#A09790]" aria-hidden="true" />
                </div>
                <div className="mt-5 flex items-center justify-between border-t border-[#EEE8E3] pt-3 text-xs text-[#938B84]">
                  <span>{formatNumber(group.bookCount)} <I18nText>本图书</I18nText></span>
                  <BookOpen size={15} strokeWidth={1.6} className="text-[#D94724] transition group-hover:translate-x-0.5" aria-hidden="true" />
                </div>
              </button>
            ))}
          </div>
          {page < totalPages ? (
            <div className="mt-8 flex justify-center">
              <Button variant="secondary" loading={loadingMore} loadingText={t('加载中')} onClick={() => void loadMore()}>
                <I18nText>加载更多</I18nText>
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
