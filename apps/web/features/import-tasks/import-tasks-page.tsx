'use client';

import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Clock, FileArchive, RefreshCw, Search, Square, Trash2, X } from 'lucide-react';
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge } from '../../components/ui/badge';
import type { BadgeTone } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useConfirm, useToast } from '../../components/ui/feedback';
import { useI18n } from '../../i18n/provider';
import { PageTitle } from '../../components/ui/page-title';
import { Progress } from '../../components/ui/progress';
import { Select } from '../../components/ui/select';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import {
  requestImportQueueClear,
  waitForImportQueueClear
} from './api/clear-queue';

type ImportTask = {
  id: string;
  origin: 'MANUAL' | 'WATCH' | 'DOWNLOAD';
  status: 'PENDING' | 'PARSING' | 'COMPLETED' | 'FAILED';
  originalName?: string | null;
  sourcePath: string;
  sourceFileExists?: boolean;
  convertedFileExists?: boolean;
  contentHash?: string | null;
  progress: number;
  message?: string | null;
  errorSummary?: string | null;
  errorCode?: string | null;
  retryable?: boolean;
  friendlyError?: string | null;
  createdAt: string;
  finishedAt?: string | null;
  monitorFolder?: { name: string; rootPath: string } | null;
  book?: { id: string; title: string } | null;
  conversion?: {
    status: 'QUEUED' | 'PROBING' | 'CONVERTING' | 'NORMALIZING' | 'VALIDATING' | 'COMPLETED' | 'FAILED';
    sourceFormat: string;
    targetFormat: string;
    outputPath?: string | null;
    progress: number;
    converterVersion?: string | null;
    retryable?: boolean;
    errorCode?: string | null;
  } | null;
  logs: Array<{ id: string; level: string; message: string; createdAt: string }>;
};

type ImportScanJob = {
  id: string;
  rootPath: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  filesScanned: number;
  candidatesFound: number;
  queuedCount: number;
  skippedCount: number;
  errorCount: number;
  restartCount: number;
};

type DeleteMode = 'record' | 'source' | 'converted';
type StatusFilter = 'ALL' | ImportTask['status'];
type PageSize = '10' | '20' | '50';

const emptySummary = { completed: 0, failed: 0 };
const statusOptions = [
  { value: 'ALL', label: '全部状态' },
  { value: 'PENDING', label: '等待中' },
  { value: 'PARSING', label: '导入中' },
  { value: 'COMPLETED', label: '已完成' },
  { value: 'FAILED', label: '失败' }
];
const pageSizeOptions = [
  { value: '10', label: '10 条/页' },
  { value: '20', label: '20 条/页' },
  { value: '50', label: '50 条/页' }
];

type ImportTasksPayload = {
  ok: boolean;
  data?: {
    tasks: ImportTask[];
    summary: typeof emptySummary;
    page: number;
    pageSize: number;
    total: number;
    totalPages: number;
  };
  error?: { message: string };
};

function normalizeImportTask(task: ImportTask): ImportTask {
  return {
    ...task,
    sourcePath: task.sourcePath ?? '',
    progress: Number.isFinite(task.progress) ? task.progress : 0,
    logs: Array.isArray(task.logs) ? task.logs : []
  };
}

function ImportLogMessage({ message }: { message: string }) {
  if (message === 'AI 标题识别失败：AI 服务计费不可用，请检查服务商套餐、账户余额和计费设置') {
    return <I18nText>AI 标题识别失败：AI 服务计费不可用，请检查服务商套餐、账户余额和计费设置</I18nText>;
  }
  return <>{message}</>;
}

function statusTone(status: ImportTask['status']) {
  if (status === 'COMPLETED') return 'green';
  if (status === 'FAILED') return 'red';
  if (status === 'PARSING') return 'amber';
  return 'slate';
}

function statusLabel(status: ImportTask['status']) {
  return { PENDING: '等待中', PARSING: '导入中', COMPLETED: '已完成', FAILED: '失败' }[status];
}

function conversionStage(task: ImportTask) {
  if (!task.conversion) return task.message ?? '正在导入读物';
  return {
    QUEUED: '等待自动转换',
    PROBING: '正在检查文件',
    CONVERTING: '正在转换为 EPUB',
    NORMALIZING: '正在修复并拆分异常 EPUB',
    VALIDATING: '正在校验章节和资源',
    COMPLETED: task.status === 'COMPLETED' ? '自动转换并导入完成' : '转换完成，正在导入书库',
    FAILED: '自动转换失败'
  }[task.conversion.status];
}

function originLabel(origin: ImportTask['origin']) {
  if (origin === 'WATCH') return '监控导入';
  if (origin === 'DOWNLOAD') return '下载导入';
  return '手动上传';
}

function sourceFileAvailable(task: ImportTask) {
  return task.sourceFileExists !== false;
}

function convertedFileAvailable(task: ImportTask) {
  return task.convertedFileExists ?? Boolean(task.conversion?.outputPath);
}

function retryActionLabel(task: ImportTask) {
  return task.conversion ? '重试自动转换' : '重试导入';
}

function retryQueueMessage(task: ImportTask) {
  return task.conversion ? '已重新加入自动转换队列' : '已重新加入导入队列';
}

export function ImportTasksPage({ embedded = false }: { embedded?: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const { locale } = useI18n();
  const [tasks, setTasks] = useState<ImportTask[]>([]);
  const [scanJobs, setScanJobs] = useState<ImportScanJob[]>([]);
  const [summary, setSummary] = useState(emptySummary);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL');
  const [pageSize, setPageSize] = useState<PageSize>('10');
  const [keywordDraft, setKeywordDraft] = useState('');
  const [keyword, setKeyword] = useState('');
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'clear' | 'rescan' | ''>('');
  const [retryingTaskId, setRetryingTaskId] = useState('');
  const [deletingTaskId, setDeletingTaskId] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<ImportTask | null>(null);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleteMode, setDeleteMode] = useState<DeleteMode>('record');
  const [deleteLibraryRecord, setDeleteLibraryRecord] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);
  const clearControllerRef = useRef<AbortController | null>(null);
  const confirm = useConfirm();
  const toast = useToast();
  const activeTask = useMemo(() => page === 1 ? tasks.find((task) => task.status === 'PARSING' || task.status === 'PENDING') ?? null : null, [page, tasks]);

  const loadActiveScanJobs = useCallback(async () => {
    const responses = await Promise.all(
      ['PENDING', 'RUNNING'].map(async (status) => {
        const response = await fetch(`/api/import-scan-jobs?status=${status}`);
        const payload = await response.json() as { ok: boolean; data?: { jobs: ImportScanJob[] }; error?: { message: string } };
        if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '读取扫描进度失败');
        return payload.data?.jobs ?? [];
      })
    );
    setScanJobs(responses.flat());
  }, []);

  const loadTasks = useCallback(async (targetPage: number) => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(targetPage), pageSize });
      if (statusFilter !== 'ALL') params.set('status', statusFilter);
      if (keyword) params.set('keyword', keyword);
      const response = await fetch(`/api/import-tasks?${params.toString()}`);
      const text = await response.text();
      const payload = text ? JSON.parse(text) as ImportTasksPayload : null;
      if (!response.ok) throw new Error(payload?.error?.message ?? `读取导入任务失败：HTTP ${response.status}`);
      if (!payload) throw new Error('读取导入任务失败：服务暂时没有返回内容');
      if (!payload.ok) throw new Error(payload.error?.message ?? '读取导入任务失败');
      if (requestId !== requestIdRef.current) return;
      const nextTotalPages = Math.max(1, Number(payload.data?.totalPages ?? 1));
      const nextPage = Math.min(nextTotalPages, Math.max(1, Number(payload.data?.page ?? targetPage)));
      setTasks((payload.data?.tasks ?? []).map(normalizeImportTask));
      setSummary({ ...emptySummary, ...(payload.data?.summary ?? {}) });
      setTotal(Math.max(0, Number(payload.data?.total ?? 0)));
      setTotalPages(nextTotalPages);
      setPage((current) => current === nextPage ? current : nextPage);
      setError('');
    } catch (reason) {
      if (requestId !== requestIdRef.current) return;
      const nextError = reason instanceof Error ? reason.message : '读取导入任务失败';
      setError(nextError);
      toast.error('读取导入任务失败', nextError);
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [keyword, pageSize, statusFilter, toast]);

  async function requestRescan() {
    setBusy('rescan');
    try {
      const response = await fetch('/api/import-tasks/rescan', { method: 'POST' });
      const text = await response.text();
      const payload = text ? JSON.parse(text) as { ok: boolean; data?: { requestedAt: string; jobs: ImportScanJob[] }; error?: { message: string } } : null;
      if (!response.ok) throw new Error(payload?.error?.message ?? `请求重新识别失败：HTTP ${response.status}`);
      if (!payload?.ok) throw new Error(payload?.error?.message ?? '请求重新识别失败');
      setMessage('已请求重新识别监控文件夹');
      setScanJobs(payload.data?.jobs ?? []);
      toast.success('已请求重新识别监控文件夹');
      setError('');
      setPage(1);
      await loadTasks(1);
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '请求重新识别失败';
      setError(nextError);
      toast.error('请求重新识别失败', nextError);
    } finally {
      setBusy('');
    }
  }

  async function clearImportQueue() {
    const confirmed = await confirm({
      title: '清理导入队列？',
      description: '清理完成前会停止领取新任务，并等待当前任务安全完成或回滚。只删除队列记录，不会删除源文件、生成文件或已入库书籍。',
      confirmLabel: '确认清理',
      tone: 'danger'
    });
    if (!confirmed) return;
    setBusy('clear');
    const controller = new AbortController();
    clearControllerRef.current?.abort();
    clearControllerRef.current = controller;
    try {
      const requested = await requestImportQueueClear(controller.signal);
      setMessage('正在停止并清理导入队列');
      const completed = await waitForImportQueueClear(requested.id, {
        signal: controller.signal
      });
      if (completed.status === 'failed') throw new Error('清理导入队列失败');
      const successMessage = '导入队列已清理';
      setMessage(successMessage);
      toast.success(successMessage);
      setError('');
      setPage(1);
      await loadTasks(1);
    } catch (reason) {
      if (controller.signal.aborted) return;
      const nextError = reason instanceof Error ? reason.message : '清理导入队列失败';
      setError(nextError);
      toast.error('清理导入队列失败', nextError);
    } finally {
      if (clearControllerRef.current === controller) {
        clearControllerRef.current = null;
        setBusy('');
      }
    }
  }

  async function retryTask(task: ImportTask) {
    setRetryingTaskId(task.id);
    try {
      const response = await fetch(`/api/import-tasks/${encodeURIComponent(task.id)}/retry`, { method: 'POST' });
      const text = await response.text();
      const payload = text ? JSON.parse(text) as { ok: boolean; error?: { message: string } } : null;
      if (!response.ok) throw new Error(payload?.error?.message ?? `重试失败：HTTP ${response.status}`);
      if (!payload?.ok) throw new Error(payload?.error?.message ?? '重试失败');
      setMessage(`${task.originalName ?? task.sourcePath} 已重新加入队列`);
      setError('');
      toast.success(retryQueueMessage(task));
      setPage(1);
      await loadTasks(1);
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '重试失败';
      setError(nextError);
      toast.error('重试失败', nextError);
    } finally {
      setRetryingTaskId('');
    }
  }

  function openDeleteTask(task: ImportTask) {
    setDeleteMode('record');
    setDeleteLibraryRecord(false);
    setDeleteTarget(task);
  }

  async function deleteTasks() {
    const targets = bulkDeleteOpen ? tasks.filter((task) => selectedIds.has(task.id)) : deleteTarget ? [deleteTarget] : [];
    if (targets.length === 0) return;
    setDeletingTaskId(bulkDeleteOpen ? 'bulk' : targets[0].id);
    try {
      let deletedLibraryRecords = 0;
      let failedFileDeletes = 0;
      for (const task of targets) {
        const response = await fetch(`/api/import-tasks/${encodeURIComponent(task.id)}`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ deleteMode, deleteLibraryRecord })
        });
        const text = await response.text();
        const payload = text ? JSON.parse(text) as { ok: boolean; data?: { deletedFiles?: number; deletedLibraryRecord?: boolean; failedFileDeletes?: Array<{ path: string; message: string }> }; error?: { message: string } } : null;
        if (!response.ok) throw new Error(payload?.error?.message ?? `删除失败：HTTP ${response.status}`);
        if (!payload?.ok) throw new Error(payload?.error?.message ?? '删除失败');
        if (payload.data?.deletedLibraryRecord) deletedLibraryRecords += 1;
        failedFileDeletes += payload.data?.failedFileDeletes?.length ?? 0;
      }
      const fileMessage = deleteMode === 'source'
        ? `已删除 ${targets.length} 条导入记录和对应源文件`
        : deleteMode === 'converted'
          ? `已删除 ${targets.length} 条导入记录和对应转换文件`
          : `已删除 ${targets.length} 条导入记录`;
      const successMessage = deletedLibraryRecords > 0 ? `${fileMessage}，并清理 ${deletedLibraryRecords} 个关联卷册` : fileMessage;
      setDeleteTarget(null);
      setBulkDeleteOpen(false);
      setSelectedIds(new Set());
      setMessage(successMessage);
      setError('');
      toast.success(successMessage, failedFileDeletes > 0 ? `有 ${failedFileDeletes} 个系统文件未能删除，请检查系统日志` : undefined);
      await loadTasks(page);
    } catch (reason) {
      const nextError = reason instanceof Error ? reason.message : '删除失败';
      setError(nextError);
      toast.error('删除导入记录失败', nextError);
    } finally {
      setDeletingTaskId('');
    }
  }

  useEffect(() => {
    void loadTasks(page);
  }, [loadTasks, page]);

  useEffect(() => {
    void loadActiveScanJobs().catch(() => undefined);
    const timer = window.setInterval(() => {
      void loadActiveScanJobs().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [loadActiveScanJobs]);

  useEffect(() => {
    setSelectedIds(new Set());
  }, [keyword, page, pageSize, statusFilter]);

  useEffect(() => () => {
    clearControllerRef.current?.abort();
  }, []);

  const selectableTasks = useMemo(() => tasks.filter((task) => task.status === 'COMPLETED' || task.status === 'FAILED'), [tasks]);
  const selectedTasks = useMemo(() => tasks.filter((task) => selectedIds.has(task.id)), [selectedIds, tasks]);
  const allPageSelected = selectableTasks.length > 0 && selectableTasks.every((task) => selectedIds.has(task.id));
  const dialogTargets = bulkDeleteOpen ? selectedTasks : deleteTarget ? [deleteTarget] : [];
  const canDeleteSources = dialogTargets.length > 0 && dialogTargets.every(sourceFileAvailable);
  const canDeleteConverted = dialogTargets.length > 0 && dialogTargets.every(convertedFileAvailable);
  const linkedBookIds = dialogTargets.flatMap((task) => task.book ? [task.book.id] : []);
  const canDeleteLibraryRecords = linkedBookIds.length === dialogTargets.length && new Set(linkedBookIds).size === linkedBookIds.length;

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setKeyword(keywordDraft.trim());
  }

  function toggleTaskSelection(taskId: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  }

  function openBulkDelete() {
    setDeleteMode('record');
    setDeleteLibraryRecord(false);
    setBulkDeleteOpen(true);
  }

  return (
    <div className={embedded ? 'space-y-4' : 'space-y-6'}>
      {!embedded ? <PageTitle
        title={i18nAttribute("导入任务")}
        desc={i18nAttribute("查看手动上传和监控文件夹自动导入状态。")}
        action={(
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" icon={RefreshCw} loading={loading} loadingText={i18nAttribute("刷新中")} onClick={() => void loadTasks(page)}><I18nText>刷新</I18nText></Button>
            <Button loading={busy === 'rescan'} loadingText={i18nAttribute("请求中")} variant="secondary" icon={Search} onClick={() => void requestRescan()}>
              <I18nText>强制重新识别</I18nText></Button>
            <Button loading={busy === 'clear'} loadingText={i18nAttribute("清理中")} variant="danger" icon={Trash2} onClick={() => void clearImportQueue()}>
              <I18nText>清理导入队列</I18nText></Button>
          </div>
        )}
      /> : (
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" icon={RefreshCw} loading={loading} loadingText={i18nAttribute("刷新中")} onClick={() => void loadTasks(page)}><I18nText>刷新</I18nText></Button>
          <Button loading={busy === 'rescan'} loadingText={i18nAttribute("请求中")} variant="secondary" icon={Search} onClick={() => void requestRescan()}><I18nText>重新识别全部文件夹</I18nText></Button>
          <Button loading={busy === 'clear'} loadingText={i18nAttribute("清理中")} variant="ghost" icon={Trash2} onClick={() => void clearImportQueue()}><I18nText>清理导入队列</I18nText></Button>
        </div>
      )}
      {scanJobs.length > 0 ? (
        <div className="space-y-2 rounded-[20px] border border-[#F0DED5] bg-[#FFF8F4] p-4">
          <div className="text-sm font-semibold text-[#3D3732]"><I18nText>活动扫描任务</I18nText></div>
          {scanJobs.map((job) => (
            <div key={job.id} className="flex flex-col gap-2 rounded-xl bg-white px-3 py-2 text-xs text-[#6D625B] md:flex-row md:items-center">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-[#3D3732]">{job.rootPath}</div>
                <div className="mt-1">
                  <I18nText>检查文件：</I18nText>{job.filesScanned} · <I18nText>发现候选：</I18nText>{job.candidatesFound} · <I18nText>加入队列：</I18nText>{job.queuedCount} · <I18nText>按规则跳过：</I18nText>{job.skippedCount} · <I18nText>错误：</I18nText>{job.errorCount} · <I18nText>重启次数：</I18nText>{job.restartCount}
                </div>
              </div>
              <Button variant="ghost" icon={Square} onClick={() => void (async () => {
                await fetch(`/api/import-scan-jobs/${encodeURIComponent(job.id)}/cancel`, { method: 'POST' });
                await loadActiveScanJobs();
              })()} aria-label={i18nAttribute("取消扫描任务")}><I18nText>取消扫描</I18nText></Button>
            </div>
          ))}
        </div>
      ) : null}
      <form onSubmit={submitSearch} className="flex flex-col gap-3 rounded-[20px] border border-[#DEDAD4] bg-[#FAF9F7] p-3 md:flex-row md:items-center">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-[#DEDAD4] bg-white px-3 focus-within:border-[#F19B84] focus-within:ring-2 focus-within:ring-[#FCE5DE]">
          <Search size={16} className="shrink-0 text-[#8A847D]" />
          <input
            value={keywordDraft}
            onChange={(event) => setKeywordDraft(event.target.value)}
            placeholder={i18nAttribute("搜索文件名、路径、图书或错误信息")}
            className="h-10 min-w-0 flex-1 bg-transparent text-sm text-[#2A2825] outline-none placeholder:text-[#A6A099]"
            aria-label={i18nAttribute("搜索导入记录")}
          />
          {keywordDraft ? <button type="button" onClick={() => { setKeywordDraft(''); setKeyword(''); setPage(1); }} className="text-[#8A847D] hover:text-[#2A2825]" aria-label={i18nAttribute("清空搜索")}><X size={15} /></button> : null}
        </label>
        <Select
          value={statusFilter}
          options={statusOptions}
          onChange={(status) => { setStatusFilter(status); setPage(1); }}
          ariaLabel={i18nAttribute("按状态筛选")}
          className="min-w-[132px]"
          triggerClassName="h-10"
          menuClassName="min-w-[160px]"
        />
        <Button type="submit" variant="secondary"><I18nText>搜索</I18nText></Button>
        {selectedIds.size > 0 ? <Button type="button" variant="danger" icon={Trash2} onClick={openBulkDelete}><I18nText>删除所选（</I18nText>{selectedIds.size}）</Button> : null}
      </form>
      {selectableTasks.length > 0 ? (
        <label className="flex w-fit cursor-pointer items-center gap-2 px-1 text-sm text-[#77716A]">
          <input
            type="checkbox"
            checked={allPageSelected}
            onChange={(event) => setSelectedIds(event.target.checked ? new Set(selectableTasks.map((task) => task.id)) : new Set())}
            className="h-4 w-4 accent-[#E64A2E]"
          />
          <I18nText>选择本页已结束记录</I18nText></label>
      ) : null}
      {message ? <div className="rounded-3xl border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-700">{message}</div> : null}
      {activeTask ? (
        <div className="rounded-[28px] border border-amber-100 bg-amber-50 p-5 text-amber-800">
          <div className="flex items-center gap-2 font-semibold"><Clock size={18} />{conversionStage(activeTask)}</div>
          <Progress value={activeTask.progress} className="mt-4" />
          <div className="mt-2 text-sm">{activeTask.originalName ?? activeTask.sourcePath}</div>
        </div>
      ) : null}
      {!embedded ? <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { label: '已完成', value: summary.completed },
          { label: '失败', value: summary.failed }
        ].map(({ label, value }) => (
          <div key={label} className="rounded-[22px] border border-slate-200 bg-white p-4 shadow-sm">
            <div className="text-xs text-slate-500">{i18nAttribute(label)}</div>
            <div className="mt-1 text-2xl font-semibold text-slate-950">{value}</div>
          </div>
        ))}
      </div> : null}
      {loading ? <div className="shuku-loading-panel p-8 text-sm" role="status" aria-live="polite"><I18nText>正在读取导入任务...</I18nText></div> : null}
      {error ? <div className="rounded-3xl border border-red-100 bg-red-50 p-8 text-sm text-red-700">{error}</div> : null}
      {!loading && !error && tasks.length === 0 ? <div className="rounded-3xl border border-slate-200 bg-white p-8 text-sm text-slate-500"><I18nText>暂无导入任务。</I18nText></div> : null}
      <div className="space-y-3">
        {tasks.map((task) => (
          <div key={task.id} className={`rounded-[28px] border bg-white p-5 shadow-sm transition ${selectedIds.has(task.id) ? 'border-[#F19B84] ring-2 ring-[#FCE5DE]' : 'border-slate-200'}`}>
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div className="flex min-w-0 flex-1 items-start gap-3">
                {task.status === 'COMPLETED' || task.status === 'FAILED' ? (
                  <input
                    type="checkbox"
                    checked={selectedIds.has(task.id)}
                    onChange={() => toggleTaskSelection(task.id)}
                    className="mt-1 h-4 w-4 shrink-0 accent-[#E64A2E]"
                    aria-label={i18nAttribute("选择 {value0}", { value0: task.originalName ?? task.sourcePath })}
                  />
                ) : <span className="w-4 shrink-0" />}
                <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <FileArchive size={18} className="text-blue-600" />
                  <span className="font-semibold">{task.book?.title ?? task.originalName ?? task.sourcePath.split('/').at(-1)}</span>
                  <Badge tone={statusTone(task.status) as BadgeTone}>{statusLabel(task.status)}</Badge>
                  <Badge>{originLabel(task.origin)}</Badge>
                  {task.conversion ? <Badge tone="blue">{task.conversion.sourceFormat} → {task.conversion.targetFormat}</Badge> : null}
                </div>
                <div className="mt-2 break-words text-sm text-slate-500">{task.monitorFolder?.name ? `${task.monitorFolder.name} · ` : ''}{task.sourcePath}</div>
                {task.conversion && task.status !== 'FAILED' ? <div className="mt-2 text-sm font-medium text-[#B45336]">{conversionStage(task)}</div> : null}
                {task.errorSummary ? (
                  <div className="mt-3 space-y-2 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">
                    <div className="flex gap-2"><AlertTriangle size={16} />{task.errorSummary}</div>
                    {task.friendlyError ? <div className="pl-6 text-red-600"><I18nText>建议：</I18nText>{task.friendlyError}</div> : null}
                    {task.retryable ? (
                      <div className="pl-6 pt-1">
                        <Button className="min-h-9 px-3 py-1.5" variant="secondary" icon={RefreshCw} loading={retryingTaskId === task.id} loadingText={i18nAttribute("正在重试")} onClick={() => void retryTask(task)}>{retryActionLabel(task)}</Button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <div className="text-sm text-slate-500">{new Date(task.createdAt).toLocaleString(locale)}</div>
                {task.status === 'COMPLETED' || task.status === 'FAILED' ? (
                  <Button className="min-h-9 px-3 py-1.5" variant="ghost" icon={Trash2} onClick={() => openDeleteTask(task)}><I18nText>删除</I18nText></Button>
                ) : null}
              </div>
            </div>
            {task.status === 'PARSING' || task.status === 'PENDING' ? <Progress value={task.progress} className="mt-4" /> : null}
            {task.logs.length > 0 ? (
              <div className="mt-4 space-y-1 rounded-2xl bg-slate-50 p-3 font-mono text-xs text-slate-500">
                {task.logs.slice(0, 5).map((log) => (
                  <div key={log.id} className="break-words">
                    <span className={log.level === 'error' ? 'text-red-600' : log.level === 'warn' ? 'text-amber-600' : 'text-slate-500'}>{log.level}</span> · <ImportLogMessage message={log.message} />
                  </div>
                ))}
              </div>
            ) : null}
            {task.status === 'COMPLETED' ? <div className="mt-4 flex items-center gap-2 text-sm text-emerald-600"><CheckCircle2 size={16} /><I18nText>导入完成</I18nText></div> : null}
          </div>
        ))}
      </div>
      {dialogTargets.length > 0 ? (
        <div className="fixed inset-0 z-[130] flex items-end justify-center bg-slate-950/45 p-0 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={i18nAttribute("删除导入记录")}>
          <div className="w-full max-w-lg rounded-t-3xl border border-slate-200 bg-white p-5 shadow-2xl md:rounded-3xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">{bulkDeleteOpen ? i18nAttribute("批量删除 {value0} 条导入记录", { value0: dialogTargets.length }) : i18nAttribute("删除导入记录")}</h2>
                <p className="mt-2 break-words text-sm leading-6 text-slate-600">{bulkDeleteOpen ? i18nAttribute("选择对所有已选记录执行的删除行为。") : i18nAttribute("选择“{value0}”的删除范围。", { value0: dialogTargets[0].originalName ?? dialogTargets[0].sourcePath })}</p>
              </div>
              <button type="button" disabled={Boolean(deletingTaskId)} onClick={() => { setDeleteTarget(null); setBulkDeleteOpen(false); }} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-slate-500 hover:bg-slate-100 disabled:opacity-50" aria-label={i18nAttribute("关闭")}><X size={18} /></button>
            </div>
            <div className="mt-5 space-y-2" role="radiogroup" aria-label={i18nAttribute("删除范围")}>
              {([
                { value: 'record' as const, label: '仅删除导入记录', description: '保留源文件和转换后的文件。', available: true },
                { value: 'source' as const, label: '同步删除源文件', description: '转换文件会保留；直接使用这些源文件的卷册将无法继续阅读。', available: canDeleteSources },
                { value: 'converted' as const, label: '同步删除转换后的文件', description: '源文件会保留；使用这些转换文件的卷册将无法继续阅读。', available: canDeleteConverted }
              ]).map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={deleteMode === option.value}
                  disabled={!option.available || Boolean(deletingTaskId)}
                  onClick={() => setDeleteMode(option.value)}
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition disabled:cursor-not-allowed disabled:opacity-45 ${deleteMode === option.value ? 'border-red-200 bg-red-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
                >
                  <span className="flex items-center justify-between gap-3 text-sm font-semibold text-slate-900">
                    {i18nAttribute(option.label)}
                    {!option.available ? <span className="text-xs font-normal text-slate-400"><I18nText>文件不存在</I18nText></span> : null}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500">{option.description}</span>
                </button>
              ))}
            </div>
            {canDeleteLibraryRecords ? (
              <label className={`mt-4 flex cursor-pointer gap-3 rounded-2xl border p-4 transition ${deleteLibraryRecord ? 'border-red-200 bg-red-50' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'}`}>
                <input type="checkbox" checked={deleteLibraryRecord} disabled={Boolean(deletingTaskId)} onChange={(event) => setDeleteLibraryRecord(event.target.checked)} className="mt-0.5 h-4 w-4 accent-red-600" />
                <span>
                  <span className="block text-sm font-semibold text-slate-900"><I18nText>同步删除关联卷册</I18nText></span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500"><I18nText>仅删除所选记录直接关联的卷册及其阅读进度和系统生成文件；同一本书的其他卷册会保留，最后一个卷册删除后才移除作品。源文件是否删除由上方选项决定。</I18nText></span>
                </span>
              </label>
            ) : (
              <div className="mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-500">{bulkDeleteOpen ? i18nAttribute("所选记录没有一一对应的独立书库图书，本次仅处理导入记录和所选文件。") : i18nAttribute("这条导入记录没有关联的书库图书，无需同步删除书库记录。")}</div>
            )}
            {deleteMode !== 'record' || deleteLibraryRecord ? <div className="mt-4 flex gap-2 rounded-2xl bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><I18nText>已选择的文件和书库数据删除后无法恢复。</I18nText></div> : null}
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="secondary" disabled={Boolean(deletingTaskId)} onClick={() => { setDeleteTarget(null); setBulkDeleteOpen(false); }}><I18nText>取消</I18nText></Button>
              <Button type="button" variant="danger" icon={Trash2} loading={Boolean(deletingTaskId)} loadingText={i18nAttribute("删除中")} onClick={() => void deleteTasks()}>{deleteMode === 'record' && !deleteLibraryRecord ? i18nAttribute("删除记录") : i18nAttribute("确认删除")}</Button>
            </div>
          </div>
        </div>
      ) : null}
      {!error && total > 0 ? (
        <footer className="flex flex-wrap items-center justify-between gap-3 pt-1 text-sm text-[#77716A]">
          <div className="flex flex-wrap items-center gap-3">
            <span><I18nText>共 </I18nText>{total} <I18nText>条记录</I18nText></span>
            <Select
              value={pageSize}
              options={pageSizeOptions}
              onChange={(size) => { setPageSize(size); setPage(1); }}
              ariaLabel={i18nAttribute("每页显示数量")}
              size="sm"
              align="left"
              className="min-w-[112px]"
              menuClassName="min-w-[128px]"
            />
          </div>
          {totalPages > 1 ? (
            <nav className="flex items-center gap-2" aria-label={i18nAttribute("导入活动分页")}>
              <button
                type="button"
                disabled={page <= 1 || loading}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40"
                aria-label={i18nAttribute("上一页")}
              >
                <ChevronLeft size={16} />
              </button>
              <span className="min-w-16 text-center text-[#4F4A45]">{page} / {totalPages}</span>
              <button
                type="button"
                disabled={page >= totalPages || loading}
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40"
                aria-label={i18nAttribute("下一页")}
              >
                <ChevronRight size={16} />
              </button>
            </nav>
          ) : null}
        </footer>
      ) : null}
    </div>
  );
}
