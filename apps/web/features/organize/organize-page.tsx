'use client';

import { ChevronLeft, ChevronRight, RefreshCw, RotateCcw, Search, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Cover } from '../../components/book/cover';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useConfirm, useToast } from '../../components/ui/feedback';
import { PageTitle } from '../../components/ui/page-title';
import { Select } from '../../components/ui/select';
import type { WorkView } from '../../types/work';

type ProviderExecution = {
  id: string;
  providerId: string;
  status: string;
  attempts: number;
  errorSummary?: string | null;
};

export type OrganizeStatusCategory = 'SUCCESS' | 'FAILED' | 'RECOGNIZING' | 'WAITING';

export type OrganizeJobView = {
  id: string;
  runId?: string | null;
  trigger?: string;
  status: string;
  statusCategory?: OrganizeStatusCategory;
  issueCodes: string[];
  reasonCodes?: string[];
  summary: string | null;
  errorSummary?: string | null;
  metadataLookupStatus?: string | null;
  metadataLookupSource?: string | null;
  metadataLookupProviders?: string[];
  metadataSources?: string[];
  providerExecutions?: ProviderExecution[];
  startedAt?: string | null;
  finishedAt?: string | null;
  createdAt?: string | null;
  updatedAt: string;
  book: WorkView;
};

type JobsResponse = {
  ok: boolean;
  data?: {
    jobs: OrganizeJobView[];
    books: WorkView[];
    page: number;
    pageSize: number;
    total: number;
    totalPages: number;
    statusCounts?: Record<OrganizeStatusCategory, number>;
  };
  error?: { message: string };
};

type ProvidersResponse = {
  ok: boolean;
  data?: { providers: Array<{ id: string; name: string }> };
};

const fallbackSourceLabels: Record<string, string> = {
  douban: '豆瓣图书',
  bangumi: 'Bangumi',
  ai: 'AI',
  embedded: '内嵌元数据',
  filename: '文件名',
  aggregation: '自动聚合',
  external: '外部数据源',
  rule: '整理规则'
};

export function normalizeOrganizeJob(job: OrganizeJobView): OrganizeJobView | null {
  if (!job?.book) return null;
  return {
    ...job,
    statusCategory: job.statusCategory ?? organizeStatusCategory(job.status, job.metadataLookupStatus),
    issueCodes: Array.isArray(job.issueCodes) ? job.issueCodes : [],
    reasonCodes: Array.isArray(job.reasonCodes) ? job.reasonCodes : [],
    metadataLookupProviders: Array.isArray(job.metadataLookupProviders) ? job.metadataLookupProviders : [],
    metadataSources: Array.isArray(job.metadataSources) ? job.metadataSources : [],
    providerExecutions: Array.isArray(job.providerExecutions) ? job.providerExecutions : [],
    book: {
      ...job.book,
      title: job.book.title ?? '未命名作品',
      author: job.book.author ?? '未知作者',
      tags: Array.isArray(job.book.tags) ? job.book.tags : []
    }
  };
}

export function organizeStatusCategory(status: string, lookupStatus?: string | null): OrganizeStatusCategory {
  const normalized = String(status || '').toUpperCase();
  const lookup = String(lookupStatus || '').toUpperCase();
  if (['APPLIED', 'COMPLETED'].includes(normalized)) return 'SUCCESS';
  if (['FAILED', 'REVIEWING', 'DISMISSED', 'CANCELLED'].includes(normalized)) return 'FAILED';
  if (normalized === 'RUNNING' || lookup === 'RUNNING') return 'RECOGNIZING';
  return 'WAITING';
}

export function organizeStatusLabel(category: OrganizeStatusCategory) {
  if (category === 'SUCCESS') return '成功';
  if (category === 'FAILED') return '失败';
  if (category === 'RECOGNIZING') return '识别中';
  return '等待中';
}

function statusTone(category: OrganizeStatusCategory): 'green' | 'red' | 'blue' | 'amber' {
  if (category === 'SUCCESS') return 'green';
  if (category === 'FAILED') return 'red';
  if (category === 'RECOGNIZING') return 'blue';
  return 'amber';
}

function reasonLabel(code: string) {
  if (code === 'MANUAL_SELECTED') return '历史手动加入';
  if (code === 'MANUAL_RECOGNIZE') return '手动重新识别';
  if (code === 'UNRECOGNIZED') return '尚未识别';
  if (code === 'MISSING_METADATA') return '缺少元数据';
  if (code === 'QUALITY_BELOW_THRESHOLD') return '元数据质量偏低';
  if (code === 'NEW_IMPORT') return '新增读物';
  if (code === 'IMPORT_FAILED') return '导入解析失败';
  if (code === 'MISSING_COVER') return '缺少封面';
  if (code === 'MISSING_AUTHOR') return '缺少作者';
  if (code === 'ODD_TITLE') return '标题异常';
  return code.replace(/^SUGGEST_/, '建议补全 ');
}

function jobReasons(job: OrganizeJobView) {
  const rawCodes = job.reasonCodes?.length ? job.reasonCodes : job.issueCodes;
  const codes = rawCodes.filter((code) => code !== 'DUPLICATE' && !code.startsWith('SUGGEST_'));
  if (codes.length) return [...new Set(codes.map(reasonLabel))];
  if (job.trigger === 'NEW') return ['新增后自动执行'];
  if (job.trigger === 'SCHEDULE') return ['定时识别'];
  if (job.trigger === 'MANUAL') return ['历史手动加入'];
  return ['历史整理任务'];
}

function jobSources(job: OrganizeJobView) {
  const values = [
    ...(job.metadataSources ?? []),
    job.metadataLookupSource,
    ...(job.providerExecutions ?? []).map((execution) => execution.providerId),
    ...(job.metadataLookupProviders ?? [])
  ];
  return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))];
}

function StatusBadge({ category }: { category: OrganizeStatusCategory }) {
  return (
    <Badge tone={statusTone(category)}>
      <span className="inline-flex items-center gap-1.5">
        {category === 'RECOGNIZING' ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" /> : null}
        {organizeStatusLabel(category)}
      </span>
    </Badge>
  );
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return { date: '—', time: '' };
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { date: String(value), time: '' };
  return {
    date: date.toLocaleDateString(),
    time: date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  };
}

export function OrganizePage({ embedded = false, jobBasePath = '/organize/jobs' }: { embedded?: boolean; jobBasePath?: string }) {
  const router = useRouter();
  const confirm = useConfirm();
  const toast = useToast();
  const [jobs, setJobs] = useState<OrganizeJobView[]>([]);
  const [providerNames, setProviderNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | OrganizeStatusCategory>('ALL');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState('20');
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [counts, setCounts] = useState<Record<OrganizeStatusCategory, number>>({ SUCCESS: 0, FAILED: 0, RECOGNIZING: 0, WAITING: 0 });
  const [busy, setBusy] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setSearchQuery(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const loadJobs = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
      if (searchQuery) params.set('search', searchQuery);
      if (statusFilter !== 'ALL') params.set('status', statusFilter);
      const [jobsResponse, providersResponse] = await Promise.all([
        fetch(`/api/organize/jobs?${params.toString()}`, { cache: 'no-store' }),
        fetch('/api/metadata/providers', { cache: 'no-store' })
      ]);
      const jobsPayload = (await jobsResponse.json()) as JobsResponse;
      const providersPayload = (await providersResponse.json()) as ProvidersResponse;
      if (!jobsPayload.ok) throw new Error(jobsPayload.error?.message ?? '读取整理记录失败');
      setJobs((jobsPayload.data?.jobs ?? []).map(normalizeOrganizeJob).filter((job): job is OrganizeJobView => job !== null));
      const nextTotalPages = Math.max(1, Number(jobsPayload.data?.totalPages ?? 1));
      const nextPage = Math.min(nextTotalPages, Math.max(1, Number(jobsPayload.data?.page ?? page)));
      setTotal(Number(jobsPayload.data?.total ?? 0));
      setTotalPages(nextTotalPages);
      if (jobsPayload.data?.statusCounts) setCounts(jobsPayload.data.statusCounts);
      if (nextPage !== page) setPage(nextPage);
      if (providersPayload.ok) {
        setProviderNames(Object.fromEntries((providersPayload.data?.providers ?? []).map((provider) => [provider.id, provider.name])));
      }
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取整理记录失败');
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [page, pageSize, searchQuery, statusFilter]);

  useEffect(() => { void loadJobs(); }, [loadJobs]);

  function sourceLabel(source: string) {
    return providerNames[source] ?? fallbackSourceLabels[source] ?? source;
  }

  async function mutateJob(job: OrganizeJobView, action: 'delete' | 'recognize') {
    if (action === 'delete' && !await confirm({
      title: '删除整理记录',
      description: `仅删除《${job.book.title}》的整理记录，不会删除书库读物或文件。`,
      confirmLabel: '删除',
      tone: 'danger'
    })) return;
    setBusy(`${action}:${job.id}`);
    try {
      const response = await fetch(
        action === 'delete' ? `/api/organize/jobs/${job.id}` : `/api/organize/jobs/${job.id}/recognize`,
        { method: action === 'delete' ? 'DELETE' : 'POST' }
      );
      const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
      if (!payload.ok) throw new Error(payload.error?.message ?? '操作失败');
      toast.success(action === 'delete' ? '整理记录已删除' : '已加入重新识别队列');
      await loadJobs(true);
    } catch (reason) {
      toast.error('操作失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
    }
  }

  return (
    <div className={embedded ? 'space-y-4' : 'space-y-6'}>
      {!embedded ? (
        <PageTitle
          title="整理队列"
          desc="查看全部整理记录；任务由定时策略或新增后自动执行产生。"
          action={<Button variant="secondary" icon={RefreshCw} onClick={() => void loadJobs()}>刷新</Button>}
        />
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm leading-6 text-[#77716A]">查看全部整理记录，跟踪每次识别的入队原因、状态与数据源。</p>
          <Button variant="ghost" icon={RefreshCw} aria-label="刷新整理记录" onClick={() => void loadJobs()}>刷新</Button>
        </div>
      )}

      {error ? <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      {!embedded ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {(['SUCCESS', 'FAILED', 'RECOGNIZING', 'WAITING'] as OrganizeStatusCategory[]).map((category) => (
            <div key={category} className="rounded-[22px] border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs text-slate-500">{organizeStatusLabel(category)}</div>
              <div className="mt-1 text-2xl font-semibold text-slate-950">{counts[category]}</div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="rounded-[28px] border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-3 border-b border-[#EAE5DF] bg-white p-4 sm:flex-row sm:items-center">
          <div className="relative min-w-0 flex-1">
            <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[#9A938C]" />
            <input
              value={search}
              onChange={(event) => { setSearch(event.target.value); setPage(1); }}
              placeholder="搜索书名、作者、入队原因或数据源"
              className="h-11 w-full rounded-xl border border-[#E2DDD7] bg-[#FCFBF9] pl-10 pr-4 text-sm outline-none focus:border-[#EF8B73]"
            />
          </div>
          <Select
            value={statusFilter}
            onChange={(value) => { setStatusFilter(value); setPage(1); }}
            ariaLabel="整理记录状态筛选"
            options={[
              { value: 'ALL', label: '全部状态' },
              { value: 'SUCCESS', label: '成功' },
              { value: 'FAILED', label: '失败' },
              { value: 'RECOGNIZING', label: '识别中' },
              { value: 'WAITING', label: '等待中' }
            ]}
            className="w-full sm:w-auto"
            triggerClassName="h-11 min-w-[132px]"
            align="right"
          />
          <span className="px-1 text-xs text-[#8B847D]">共 {total} 条</span>
        </div>

        {loading ? <div className="shuku-loading-panel p-8 text-sm" role="status" aria-live="polite">正在读取整理记录...</div> : null}
        {!loading && jobs.length === 0 ? <div className="p-10 text-center text-sm text-slate-500">{searchQuery || statusFilter !== 'ALL' ? '没有符合当前筛选条件的记录。' : '尚无整理记录。任务会在定时策略或新增后自动执行时产生。'}</div> : null}

        {!loading && jobs.length > 0 ? (
          <>
            <div className="divide-y divide-slate-100 md:hidden">
              {jobs.map((job) => {
                const category = job.statusCategory ?? 'WAITING';
                const reasons = jobReasons(job);
                const sources = jobSources(job);
                const time = formatDateTime(job.createdAt ?? job.updatedAt);
                return (
                  <article key={job.id} data-testid="organize-job-mobile-card" className="p-4">
                    <button type="button" onClick={() => router.push(`${jobBasePath}/${job.id}`)} className="flex w-full min-w-0 items-center gap-3 text-left">
                      <Cover book={job.book} className="h-16 w-12 shrink-0 rounded-lg" small />
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-2 font-semibold leading-5 text-slate-900">{job.book.title}</span>
                        <span className="mt-1 block truncate text-xs text-slate-500">{job.book.author} · {job.book.format}</span>
                      </span>
                      <StatusBadge category={category} />
                    </button>
                    <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-slate-100 pt-4 text-sm">
                      <div><dt className="text-xs text-slate-500">入队原因</dt><dd className="mt-1 flex flex-wrap gap-1">{reasons.slice(0, 2).map((reason) => <Badge key={reason} tone="slate">{reason}</Badge>)}</dd></div>
                      <div><dt className="text-xs text-slate-500">数据源</dt><dd className="mt-1 flex flex-wrap gap-1">{sources.length ? sources.slice(0, 2).map((source) => <Badge key={source} tone="blue">{sourceLabel(source)}</Badge>) : <span className="text-slate-400">—</span>}</dd></div>
                      <div><dt className="text-xs text-slate-500">入队时间</dt><dd className="mt-1 text-xs leading-5 text-slate-700">{time.date} {time.time}</dd></div>
                      <div className="col-span-2 flex flex-wrap justify-end gap-2">
                        <Button variant="secondary" icon={RotateCcw} className="min-h-9 px-3 py-1.5 text-xs" loading={busy === `recognize:${job.id}`} loadingText="入队中" disabled={Boolean(busy)} onClick={() => void mutateJob(job, 'recognize')}>重新识别</Button>
                        <Button variant="danger" icon={Trash2} className="min-h-9 px-3 py-1.5 text-xs" loading={busy === `delete:${job.id}`} loadingText="删除中" disabled={Boolean(busy)} onClick={() => void mutateJob(job, 'delete')}>删除</Button>
                      </div>
                    </dl>
                  </article>
                );
              })}
            </div>

            <div data-testid="organize-job-desktop-table" className="hidden md:block">
              <table className="w-full table-fixed text-left text-sm">
                <thead className="bg-[#FAF9F7] text-xs text-[#716B64]">
                  <tr>
                    <th className="w-[24%] px-5 py-4 font-medium">读物</th>
                    <th className="w-[19%] px-3 py-4 font-medium">入队原因</th>
                    <th className="w-[12%] px-3 py-4 font-medium">状态</th>
                    <th className="w-[18%] px-3 py-4 font-medium">数据源</th>
                    <th className="w-[12%] px-3 py-4 font-medium">入队时间</th>
                    <th className="w-[15%] px-5 py-4 text-right font-medium">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {jobs.map((job) => {
                    const category = job.statusCategory ?? 'WAITING';
                    const reasons = jobReasons(job);
                    const sources = jobSources(job);
                    const time = formatDateTime(job.createdAt ?? job.updatedAt);
                    return (
                      <tr key={job.id} className="transition-colors hover:bg-[#FCFBF9]">
                        <td className="px-5 py-4 align-middle">
                          <button type="button" onClick={() => router.push(`${jobBasePath}/${job.id}`)} className="flex w-full min-w-0 items-center gap-3 text-left">
                            <Cover book={job.book} className="h-12 w-9 shrink-0 rounded-lg" small />
                            <span className="min-w-0"><span className="block truncate font-semibold text-slate-900">{job.book.title}</span><span className="mt-1 block truncate text-xs text-slate-500">{job.book.author} · {job.book.format}</span></span>
                          </button>
                        </td>
                        <td className="px-3 py-4 align-middle"><div className="flex min-w-0 flex-wrap gap-1">{reasons.slice(0, 2).map((reason) => <Badge key={reason} tone="slate">{reason}</Badge>)}{reasons.length > 2 ? <span className="text-xs text-slate-400">+{reasons.length - 2}</span> : null}</div></td>
                        <td className="px-3 py-4 align-middle"><StatusBadge category={category} /></td>
                        <td className="px-3 py-4 align-middle"><div className="flex min-w-0 flex-wrap gap-1">{sources.length ? sources.slice(0, 2).map((source) => <Badge key={source} tone="blue">{sourceLabel(source)}</Badge>) : <span className="text-slate-400">—</span>}{sources.length > 2 ? <span className="text-xs text-slate-400">+{sources.length - 2}</span> : null}</div></td>
                        <td className="px-3 py-4 align-middle text-xs leading-5 text-slate-500"><span className="block">{time.date}</span><span className="block tabular-nums">{time.time}</span></td>
                        <td className="px-5 py-4 align-middle">
                          <div className="flex flex-wrap justify-end gap-1.5">
                            <Button variant="ghost" icon={RotateCcw} className="min-h-8 px-2.5 py-1.5 text-xs" loading={busy === `recognize:${job.id}`} loadingText="入队中" disabled={Boolean(busy)} onClick={() => void mutateJob(job, 'recognize')}>重新识别</Button>
                            <Button variant="ghost" icon={Trash2} className="min-h-8 px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50 hover:text-red-700" loading={busy === `delete:${job.id}`} loadingText="删除中" disabled={Boolean(busy)} onClick={() => void mutateJob(job, 'delete')}>删除</Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : null}

        {!loading && total > 0 ? (
          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-[#EAE5DF] px-4 py-3 text-sm text-[#77716A] sm:px-5">
            <div className="flex items-center gap-3">
              <span>共 {total} 条记录</span>
              <Select
                value={pageSize}
                onChange={(value) => { setPageSize(value); setPage(1); }}
                ariaLabel="每页显示数量"
                options={[
                  { value: '20', label: '每页 20 条' },
                  { value: '50', label: '每页 50 条' },
                  { value: '100', label: '每页 100 条' }
                ]}
                size="sm"
                align="left"
                className="min-w-[118px]"
              />
            </div>
            <nav className="flex items-center gap-2" aria-label="识别记录分页">
              <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40" aria-label="上一页"><ChevronLeft size={16} /></button>
              <span className="min-w-16 text-center text-[#4F4A45]">{page} / {totalPages}</span>
              <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((current) => Math.min(totalPages, current + 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40" aria-label="下一页"><ChevronRight size={16} /></button>
            </nav>
          </footer>
        ) : null}
      </div>
    </div>
  );
}
