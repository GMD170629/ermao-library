'use client';

import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Clock, FileArchive, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Badge } from '../../components/ui/badge';
import type { BadgeTone } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useToast } from '../../components/ui/feedback';
import { I18nText, useI18n } from '../../i18n/provider';
import { PageTitle } from '../../components/ui/page-title';
import { Select } from '../../components/ui/select';
import {
  continueSourceImport,
  fetchImportLibraries,
  fetchImportTasks,
  type ImportLibrary,
  type ImportTaskState,
  type LibraryImportTask
} from './public';

type ImportTaskStateFilter = 'ALL' | ImportTaskState;
type PageSize = 10 | 20 | 50;

const pageSizes: readonly PageSize[] = [10, 20, 50];

function statusTone(state: ImportTaskState): BadgeTone {
  if (state === 'SUCCEEDED') return 'green';
  if (state === 'FAILED') return 'red';
  if (state === 'RUNNING') return 'amber';
  return 'slate';
}

function statusLabel(state: ImportTaskState): string {
  return {
    QUEUED: '等待中',
    RUNNING: '导入中',
    SUCCEEDED: '已完成',
    FAILED: '失败'
  }[state];
}

function kindLabel(kind: LibraryImportTask['kind']): string {
  return {
    SCAN_LIBRARY: '扫描书库',
    CONTINUE_SOURCE: '扫描来源',
    IMPORT_ASSET: '导入资源资产'
  }[kind];
}

function roleLabel(role: NonNullable<LibraryImportTask['role']>): string {
  return {
    PRIMARY: '主文件',
    TRACK: '音轨',
    PAGE: '页面',
    SIDECAR: '元数据附属文件',
    SUPPLEMENT: '补充文件'
  }[role];
}

function taskTitle(task: LibraryImportTask): string {
  if (task.kind === 'SCAN_LIBRARY') return task.libraryName ?? task.libraryId;
  if (task.kind === 'CONTINUE_SOURCE') {
    return task.sourceRelativePath ?? task.sourceName ?? task.sourceNodeId ?? task.libraryName ?? task.libraryId;
  }
  return task.sourceRelativePath ?? task.sourceName ?? task.resourceTitle ?? task.resourceId ?? task.sourceNodeId ?? task.libraryName ?? task.libraryId;
}

function taskContext(task: LibraryImportTask): string[] {
  if (task.kind === 'SCAN_LIBRARY') return [];
  if (task.kind === 'CONTINUE_SOURCE') return [task.libraryName].filter((value): value is string => Boolean(value));
  return [task.bookTitle, task.resourceTitle, task.libraryName]
    .filter((value): value is string => Boolean(value))
    .filter((value, index, values) => values.indexOf(value) === index && value !== taskTitle(task));
}

function completionLabel(kind: LibraryImportTask['kind']): string {
  if (kind === 'SCAN_LIBRARY') return '书库扫描完成';
  if (kind === 'CONTINUE_SOURCE') return '来源扫描完成';
  return '本项导入完成';
}

function taskDate(value: string | null, locale: string): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale);
}

export function ImportTasksPage({ embedded = false }: { embedded?: boolean }) {
  const { t, locale } = useI18n();
  const toast = useToast();
  const [libraries, setLibraries] = useState<ImportLibrary[]>([]);
  const [selectedLibraryId, setSelectedLibraryId] = useState('');
  const [librariesLoading, setLibrariesLoading] = useState(true);
  const [tasks, setTasks] = useState<LibraryImportTask[]>([]);
  const [summary, setSummary] = useState({ queued: 0, running: 0, completed: 0, failed: 0 });
  const [page, setPage] = useState(1);
  const [stateFilter, setStateFilter] = useState<ImportTaskStateFilter>('ALL');
  const [pageSize, setPageSize] = useState<PageSize>(10);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [continuingTaskId, setContinuingTaskId] = useState('');
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    setLibrariesLoading(true);
    void fetchImportLibraries(controller.signal)
      .then((next) => {
        const enabled = next.filter((library) => library.enabled);
        setLibraries(enabled);
        setSelectedLibraryId((current) => enabled.some((library) => library.id === current) ? current : enabled[0]?.id ?? '');
        if (enabled.length === 0) setError(t('未找到可访问的书库'));
      })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        const message = reason instanceof Error ? reason.message : t('读取书库失败');
        setError(message);
        toast.error(t('读取书库失败'), message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLibrariesLoading(false);
      });
    return () => controller.abort();
  }, [t, toast]);

  const loadTasks = useCallback(async (targetPage: number, signal?: AbortSignal, silent = false) => {
    const requestId = ++requestIdRef.current;
    if (!selectedLibraryId) {
      setTasks([]);
      setSummary({ queued: 0, running: 0, completed: 0, failed: 0 });
      setTotal(0);
      setTotalPages(1);
      setLoading(false);
      return;
    }
    if (!silent) setLoading(true);
    try {
      const result = await fetchImportTasks(selectedLibraryId, targetPage, pageSize, stateFilter === 'ALL' ? null : stateFilter, signal);
      if (requestId !== requestIdRef.current) return;
      const nextPage = Math.min(result.totalPages, Math.max(1, result.page));
      setTasks(result.tasks);
      setSummary(result.summary);
      setTotal(result.total);
      setTotalPages(result.totalPages);
      setPage((current) => current === nextPage ? current : nextPage);
      setError('');
    } catch (reason) {
      if (signal?.aborted || requestId !== requestIdRef.current) return;
      const message = reason instanceof Error ? reason.message : t('读取导入任务失败');
      if (silent) return;
      setError(message);
      toast.error(t('读取导入任务失败'), message);
    } finally {
      if (!silent && !signal?.aborted && requestId === requestIdRef.current) setLoading(false);
    }
  }, [pageSize, selectedLibraryId, stateFilter, t, toast]);

  useEffect(() => {
    const controller = new AbortController();
    void loadTasks(page, controller.signal);
    return () => controller.abort();
  }, [loadTasks, page]);

  const activeImportCount = summary.queued + summary.running;

  useEffect(() => {
    if (!selectedLibraryId || activeImportCount === 0) return;
    let controller: AbortController | null = null;
    const refreshActiveTasks = () => {
      if (document.visibilityState !== 'visible') return;
      controller?.abort();
      controller = new AbortController();
      void loadTasks(page, controller.signal, true);
    };
    const intervalId = window.setInterval(refreshActiveTasks, 2_000);
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') refreshActiveTasks();
    };
    document.addEventListener('visibilitychange', refreshWhenVisible);
    window.addEventListener('focus', refreshActiveTasks);
    return () => {
      controller?.abort();
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
      window.removeEventListener('focus', refreshActiveTasks);
    };
  }, [activeImportCount, loadTasks, page, selectedLibraryId]);

  async function continueTask(task: LibraryImportTask) {
    if (task.state !== 'FAILED' || !task.sourceNodeId) return;
    setContinuingTaskId(task.id);
    try {
      const result = await continueSourceImport(task.sourceNodeId);
      if (result.requeuedFailed > 0 || result.enqueued) {
        toast.success(t('已重新加入导入队列'));
      } else {
        toast.success(t('没有新的导入任务'));
      }
      setError('');
      await loadTasks(page);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t('继续导入失败');
      setError(message);
      toast.error(t('继续导入失败'), message);
    } finally {
      setContinuingTaskId('');
    }
  }

  function changeStateFilter(next: ImportTaskStateFilter) {
    setStateFilter(next);
    setPage(1);
  }

  return (
    <div className={embedded ? 'space-y-4' : 'space-y-6'}>
      {!embedded ? (
        <PageTitle
          title={t('导入任务')}
          desc={t('查看书库扫描、资源继续导入和资源资产导入状态。')}
          action={(
            <Button variant="secondary" icon={RefreshCw} loading={loading} loadingText={t('刷新中')} onClick={() => void loadTasks(page)}>
              <I18nText>刷新</I18nText>
            </Button>
          )}
        />
      ) : (
        <div className="flex justify-end">
          <Button variant="secondary" icon={RefreshCw} loading={loading} loadingText={t('刷新中')} onClick={() => void loadTasks(page)}>
            <I18nText>刷新</I18nText>
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 rounded-[20px] border border-[#DEDAD4] bg-[#FAF9F7] p-3">
        <Select
          value={selectedLibraryId}
          options={libraries.map((library) => ({ value: library.id, label: library.name, translate: false }))}
          onChange={(value) => { setSelectedLibraryId(value); setPage(1); }}
          ariaLabel={t('书库')}
          disabled={librariesLoading || libraries.length === 0}
          className="min-w-[180px]"
          triggerClassName="h-10"
          menuClassName="min-w-[220px]"
        />
        <span className="text-sm font-medium text-[#4F4A45]"><I18nText>按状态筛选</I18nText></span>
        <Select
          value={stateFilter}
          options={[
            { value: 'ALL', label: t('全部状态') },
            { value: 'QUEUED', label: t('等待中') },
            { value: 'RUNNING', label: t('导入中') },
            { value: 'SUCCEEDED', label: t('已完成') },
            { value: 'FAILED', label: t('失败') }
          ]}
          onChange={changeStateFilter}
          ariaLabel={t('按状态筛选')}
          className="min-w-[132px]"
          triggerClassName="h-10"
          menuClassName="min-w-[160px]"
        />
        <span className="text-sm text-[#77716A]"><I18nText>每页显示数量</I18nText></span>
        <Select
          value={String(pageSize)}
          options={pageSizes.map((size) => ({ value: String(size), label: `${size} ${t('条/页')}` }))}
          onChange={(value) => { setPageSize(Number(value) as PageSize); setPage(1); }}
          ariaLabel={t('每页显示数量')}
          className="min-w-[112px]"
          triggerClassName="h-10"
          menuClassName="min-w-[128px]"
        />
      </div>

      {!embedded ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {[
            { label: '等待中', value: summary.queued },
            { label: '导入中', value: summary.running },
            { label: '已完成', value: summary.completed },
            { label: '失败', value: summary.failed },
            { label: '筛选结果', value: total }
          ].map(({ label, value }) => (
            <div key={label} className="rounded-[22px] border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-xs text-slate-500">{t(label)}</div>
              <div className="mt-1 text-2xl font-semibold text-slate-950">{value}</div>
            </div>
          ))}
        </div>
      ) : null}

      {activeImportCount > 0 ? (
        <div className="rounded-[28px] border border-amber-100 bg-amber-50 p-5 text-amber-800">
          <div className="flex items-center gap-2 font-semibold"><Clock size={18} /><I18nText>导入进行中</I18nText></div>
          <div className="mt-2 text-sm">{t('还有 {value0} 个任务正在处理', { value0: activeImportCount })}</div>
          <div className="mt-1 text-xs text-amber-700">{t('等待中 {value0} · 运行中 {value1}', { value0: summary.queued, value1: summary.running })}</div>
        </div>
      ) : null}

      {loading ? <div className="shuku-loading-panel p-8 text-sm" role="status" aria-live="polite"><I18nText>正在读取导入任务...</I18nText></div> : null}
      {error ? <div className="rounded-3xl border border-red-100 bg-red-50 p-5 text-sm text-red-700">{error}</div> : null}
      {!loading && !error && tasks.length === 0 ? <div className="rounded-3xl border border-slate-200 bg-white p-8 text-sm text-slate-500"><I18nText>暂无导入任务。</I18nText></div> : null}

      <div className="space-y-3">
        {tasks.map((task) => (
          <div key={task.id} className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div className="flex min-w-0 flex-1 items-start gap-3">
                <FileArchive size={18} className="mt-0.5 shrink-0 text-blue-600" />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span><I18nText>{kindLabel(task.kind)}</I18nText></span>
                    <Badge tone={statusTone(task.state)}>{t(statusLabel(task.state))}</Badge>
                    {task.role ? <Badge>{t(roleLabel(task.role))}</Badge> : null}
                  </div>
                  <div data-i18n-skip className="mt-2 break-all text-sm font-medium text-slate-700">{taskTitle(task)}</div>
                  {taskContext(task).length > 0 ? <div data-i18n-skip className="mt-1 break-all text-xs text-slate-500">{taskContext(task).join(' · ')}</div> : null}
                  <details className="mt-2 text-xs text-slate-400">
                    <summary className="cursor-pointer select-none text-slate-500"><I18nText>技术信息</I18nText></summary>
                    <div data-i18n-skip className="mt-2 break-all font-mono leading-5">
                      task: {task.id}<br />library: {task.libraryId}
                      {task.resourceId ? <><br />resource: {task.resourceId}</> : null}
                      {task.sourceNodeId ? <><br />source: {task.sourceNodeId}</> : null}
                    </div>
                  </details>
                  {task.errorSummary ? <div className="mt-3 flex gap-2 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><span>{task.errorSummary}</span></div> : null}
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-2 text-sm text-slate-500">
                <span>{taskDate(task.createdAt, locale)}</span>
                {task.state === 'FAILED' && task.sourceNodeId ? (
                  <Button className="min-h-9 px-3 py-1.5" variant="secondary" loading={continuingTaskId === task.id} loadingText={t('继续中')} onClick={() => void continueTask(task)}>
                    <I18nText>继续导入</I18nText>
                  </Button>
                ) : null}
              </div>
            </div>
            {task.state === 'SUCCEEDED' ? <div className="mt-4 flex items-center gap-2 text-sm text-emerald-600"><CheckCircle2 size={16} /><I18nText>{completionLabel(task.kind)}</I18nText></div> : null}
          </div>
        ))}
      </div>

      {!error && total > 0 ? (
        <footer className="flex flex-wrap items-center justify-between gap-3 pt-1 text-sm text-[#77716A]">
          <span><I18nText>共 </I18nText>{total} <I18nText>条记录</I18nText></span>
          {totalPages > 1 ? (
            <nav className="flex items-center gap-2" aria-label={t('导入活动分页')}>
              <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40" aria-label={t('上一页')}><ChevronLeft size={16} /></button>
              <span className="min-w-16 text-center text-[#4F4A45]">{page} / {totalPages}</span>
              <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((current) => Math.min(totalPages, current + 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40" aria-label={t('下一页')}><ChevronRight size={16} /></button>
            </nav>
          ) : null}
        </footer>
      ) : null}
    </div>
  );
}
