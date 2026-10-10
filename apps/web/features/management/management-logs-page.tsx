'use client';

import { ChevronDown, ChevronLeft, ChevronRight, Copy, Download, MessageCircleWarning, RefreshCw, Save, Search, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Badge, type BadgeTone } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Select } from '../../components/ui/select';
import { useConfirm, useToast } from '../../components/ui/feedback';
import { PageTitle } from '../../components/ui/page-title';
import { useI18n } from '../../i18n/provider';
import { ManagementNav } from './management-nav';
import { ignoredImportEventSummary } from './system-event-presentation';
import {
  clearManagementEvents,
  downloadManagementLogFiles,
  fetchManagementEventDetail,
  fetchManagementEvents,
  updateSystemLogLimit,
  type EventStorage,
  type ManagementEvent
} from './api/events';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { FeedbackDialog } from '../feedback/public';

function tone(level: string): BadgeTone {
  if (level === 'error') return 'red';
  if (level === 'warning' || level === 'warn') return 'amber';
  return 'slate';
}

function levelLabel(level: string) {
  return { debug: '调试', info: '信息', warning: '警告', warn: '警告', error: '错误' }[level] ?? level;
}

function sourceLabel(source: string) {
  return { import: '导入', download: '下载', folder: '书库', kindle: 'Kindle', library: '书库', system: '系统' }[source] ?? source;
}


type DiagnosticMetadata = {
  exceptionType?: unknown;
  location?: unknown;
  stage?: unknown;
  message?: unknown;
  traceback?: unknown;
  truncated?: unknown;
};

function readDiagnostics(metadata: Record<string, unknown> | undefined): DiagnosticMetadata | null {
  const value = metadata?.diagnostics;
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as DiagnosticMetadata) : null;
}

function diagnosticText(value: unknown) {
  return typeof value === 'string' ? value : '';
}

function DiagnosticDetails({ event, loading }: { event: ManagementEvent; loading: boolean }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const diagnostics = readDiagnostics(event.metadata);
  if (!diagnostics) return null;
  const traceback = diagnosticText(diagnostics.traceback);
  const labelClass = 'text-[#969089]';

  async function copyTraceback() {
    if (!traceback) return;
    try {
      await navigator.clipboard.writeText(traceback);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mt-3 rounded-xl border border-red-100 bg-red-50/60 p-3 text-xs leading-5 text-[#68625C]">
      <div><span className={labelClass}>{t('异常类型：')}</span><span data-i18n-skip>{diagnosticText(diagnostics.exceptionType) || '—'}</span></div>
      {diagnosticText(diagnostics.message) ? <div><span className={labelClass}>{t('异常信息：')}</span><span data-i18n-skip>{diagnosticText(diagnostics.message)}</span></div> : null}
      {diagnostics.truncated ? <p className="mt-1 text-[#B45309]">{t('堆栈信息已截断')}</p> : null}
      {loading && !traceback ? <p className="mt-2 text-[#918A83]">{t('加载堆栈中…')}</p> : null}
      {traceback ? (
        <>
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className={labelClass}>{t('堆栈信息')}</span>
            <button type="button" onClick={() => void copyTraceback()} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-[#E4D4CE] bg-white px-2 text-[11px] font-medium text-[#C83B23] hover:bg-[#FCE5DE]">
              <Copy size={12} />
              {copied ? t('已复制堆栈') : t('复制堆栈')}
            </button>
          </div>
          <pre data-i18n-skip className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-white p-2 text-[11px] text-[#4F4A45]">{traceback}</pre>
        </>
      ) : null}
    </div>
  );
}

export function ManagementLogsPage({ embedded = false }: { embedded?: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const { locale } = useI18n();
  const [events, setEvents] = useState<ManagementEvent[]>([]);
  const [source, setSource] = useState('');
  const [level, setLevel] = useState('');
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [expandedEventId, setExpandedEventId] = useState('');
  const [eventDetails, setEventDetails] = useState<Record<string, ManagementEvent>>({});
  const [detailLoading, setDetailLoading] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const [storage, setStorage] = useState<EventStorage>({ sizeBytes: 0, retentionDays: 3, minimumLevel: 'error' });
  const [retentionDays, setRetentionDays] = useState(3);
  const [minimumLevel, setMinimumLevel] = useState<EventStorage['minimumLevel']>('error');
  const [savingLimit, setSavingLimit] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [feedbackEventId, setFeedbackEventId] = useState<string | null>(null);
  const toast = useToast();
  const confirm = useConfirm();

  const buildParams = useCallback((targetPage: number, pageSize = 40) => {
    const params = new URLSearchParams({ page: String(targetPage), pageSize: String(pageSize) });
    if (source) params.set('source', source);
    if (level) params.set('level', level);
    if (appliedSearch) params.set('search', appliedSearch);
    return params;
  }, [appliedSearch, level, source]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchManagementEvents(buildParams(page));
      setEvents(payload.events);
      setTotal(payload.total);
      setTotalPages(Math.max(1, payload.totalPages));
      setStorage(payload.storage);
      setRetentionDays(payload.storage.retentionDays);
      setMinimumLevel(payload.storage.minimumLevel);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取日志失败');
    } finally {
      setLoading(false);
    }
  }, [buildParams, page]);

  async function clearLogs() {
    if (clearing || !await confirm({
      title: '清空全部系统日志？',
      description: '这将永久删除全部系统日志，包括错误和关键审计事件。此操作无法撤销。',
      confirmLabel: '全部清空',
      tone: 'danger'
    })) return;
    setClearing(true);
    let deleted: number;
    try {
      deleted = await clearManagementEvents();
    } catch (reason) {
      toast.error('清理日志失败', reason instanceof Error ? reason.message : '请稍后重试');
      return;
    } finally {
      setClearing(false);
    }
    setExpandedEventId('');
    setEventDetails({});
    toast.success(`已清理 ${deleted} 条日志`);
    if (page === 1) await load();
    else setPage(1);
  }

  async function saveLogLimit() {
    if (!Number.isInteger(retentionDays) || retentionDays < 1 || retentionDays > 365) {
      toast.error('日志保留天数无效', '保留天数必须在 1 到 365 天之间');
      return;
    }
    const nextDays = retentionDays;
    if (nextDays < storage.retentionDays && !await confirm({
      title: '缩短日志保留天数？',
      description: '缩短保留天数会立即删除过期日志文件，是否继续？',
      confirmLabel: '继续保存',
      tone: 'danger'
    })) return;
    setSavingLimit(true);
    try {
      setStorage(await updateSystemLogLimit(nextDays, minimumLevel));
      toast.success('日志设置已保存');
      await load();
    } catch (reason) {
      toast.error('保存日志设置失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setSavingLimit(false);
    }
  }

  async function toggleEvent(eventId: string) {
    if (expandedEventId === eventId) {
      setExpandedEventId('');
      return;
    }
    setExpandedEventId(eventId);
    if (eventDetails[eventId]) return;
    setDetailLoading((current) => ({ ...current, [eventId]: true }));
    try {
      const detail = await fetchManagementEventDetail(eventId);
      setEventDetails((current) => ({ ...current, [eventId]: detail }));
    } catch {
      // Keep the list summary; the stack simply stays unavailable.
    } finally {
      setDetailLoading((current) => {
        const next = { ...current };
        delete next[eventId];
        return next;
      });
    }
  }

  function applySearch() {
    const nextSearch = search.trim();
    if (nextSearch === appliedSearch && page === 1) {
      void load();
      return;
    }
    setAppliedSearch(nextSearch);
    setPage(1);
  }

  async function exportLogs() {
    setExporting(true);
    try {
      const blob = await downloadManagementLogFiles();
      const href = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = href;
      link.download = 'shuku-system-logs.zip';
      link.click();
      URL.revokeObjectURL(href);
      toast.success('日志原文件已导出');
    } catch (reason) {
      toast.error('导出日志失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setExporting(false);
    }
  }

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className={embedded ? 'space-y-4' : 'space-y-6'}>
      {!embedded ? <PageTitle title={i18nAttribute("系统日志")} desc={i18nAttribute("按级别、来源和关键字查看系统事件。")} action={<Button variant="secondary" icon={RefreshCw} loading={loading} loadingText={i18nAttribute("刷新中")} onClick={() => void load()}><I18nText>刷新</I18nText></Button>} /> : null}
      {!embedded ? <ManagementNav /> : null}
      <section className="rounded-[22px] border border-[#DEDAD4] bg-white p-4" aria-labelledby="log-storage-title">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 id="log-storage-title" className="text-sm font-semibold text-[#2A2825]"><I18nText>日志保留设置</I18nText></h2>
            <p className="mt-1 text-xs leading-5 text-[#918A83]">
              {i18nAttribute('按天保存（包含今天） · 当前 {size} MB', { size: (storage.sizeBytes / 1024 / 1024).toLocaleString(locale, { maximumFractionDigits: 2 }) })}
            </p>
          </div>
          <div className="flex w-full flex-wrap items-end gap-3 sm:w-auto">
            <label className="text-xs text-[#716B64]">
              <I18nText>保留天数</I18nText>
              <input
                type="number"
                min={1}
                max={365}
                step={1}
                value={retentionDays}
                onChange={(event) => setRetentionDays(Number(event.target.value))}
                className="mt-1 block h-11 w-24 rounded-xl border border-[#DEDAD4] px-3 text-sm text-[#2A2825] outline-none focus:border-[#F0A28F] focus:ring-2 focus:ring-[#FAD9D0]"
              />
            </label>
            <div className="grid gap-1 text-xs text-[#716B64]">
              <span><I18nText>最低记录级别</I18nText></span>
              <Select
                value={minimumLevel}
                onChange={setMinimumLevel}
                ariaLabel="最低记录级别"
                options={(['debug', 'info', 'warning', 'error'] as const).map((value) => ({ value, label: levelLabel(value) }))}
              />
            </div>
            <Button variant="secondary" icon={Save} loading={savingLimit} loadingText={i18nAttribute("保存中")} onClick={() => void saveLogLimit()}><I18nText>保存</I18nText></Button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[#EEEAE6] pt-4" aria-label={i18nAttribute("日志筛选")}>
          <Select value={level} onChange={(value) => { setLevel(value); setPage(1); }} ariaLabel="级别"
            options={['', 'debug', 'info', 'warning', 'error'].map((value) => ({ value, label: value ? levelLabel(value) : '全部级别' }))} />
          <Select value={source} onChange={(value) => { setSource(value); setPage(1); }} ariaLabel="来源"
            options={['', 'import', 'download', 'folder', 'library', 'system'].map((value) => ({ value, label: value ? sourceLabel(value) : '全部来源' }))} />
          <div className="flex min-w-0 basis-full items-center gap-2 sm:min-w-64 sm:flex-1 sm:basis-auto">
            <label className="flex h-11 min-w-0 flex-1 items-center gap-2 rounded-xl border border-[#DEDAD4] px-3 focus-within:border-[#F0A28F] focus-within:ring-2 focus-within:ring-[#FAD9D0]">
              <span className="sr-only"><I18nText>关键字</I18nText></span>
              <Search size={15} className="shrink-0 text-[#958F88]" />
              <input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') applySearch(); }} className="min-w-0 w-full bg-transparent text-sm text-[#2A2825] outline-none" placeholder={i18nAttribute("搜索错误信息")} />
            </label>
            <Button variant="secondary" onClick={applySearch}><I18nText>搜索</I18nText></Button>
          </div>
          <div className="flex flex-wrap items-center gap-1">
            <Button variant="ghost" icon={RefreshCw} loading={loading} loadingText={i18nAttribute("刷新中")} onClick={() => void load()}><I18nText>刷新</I18nText></Button>
            <Button variant="ghost" icon={Download} loading={exporting} loadingText={i18nAttribute("导出中")} onClick={() => void exportLogs()}><I18nText>导出</I18nText></Button>
            <Button variant="ghost" icon={Trash2} loading={clearing} loadingText={i18nAttribute('清理中')} onClick={() => void clearLogs()}><I18nText>清理</I18nText></Button>
            <Button variant="ghost" icon={MessageCircleWarning} onClick={() => setFeedbackEventId('')}>{i18nAttribute('报告问题')}</Button>
          </div>
        </div>
      </section>

      {error ? <div className="rounded-2xl border border-red-100 bg-red-50 p-4 text-sm text-red-700">{error}</div> : null}

      <div className="space-y-3 md:hidden">
        {!loading && events.length === 0 ? <div className="rounded-[22px] border border-[#DEDAD4] bg-white px-5 py-10 text-center text-sm text-[#817B75]"><I18nText>当前筛选条件下暂无日志。</I18nText></div> : null}
        {events.map((event) => {
          const expanded = expandedEventId === event.id;
          const summary = event.level === 'error' || event.metadata.diagnostics ? event.message : ignoredImportEventSummary(event, i18nAttribute) ?? i18nAttribute(event.message);
          return (
            <article key={event.id} data-testid="system-event-mobile-card" className="rounded-[22px] border border-[#DEDAD4] bg-white p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={tone(event.level)}>{levelLabel(event.level)}</Badge>
                <Badge tone="slate">{sourceLabel(event.source)}</Badge>
                <time className="text-xs tabular-nums text-[#77716A]">{new Date(event.createdAt).toLocaleString(locale)}</time>
              </div>
              <p data-i18n-skip className="mt-3 break-words text-sm font-medium leading-6 text-[#2A2825]">{summary}</p>
              {expanded ? (
                <div className="mt-3 rounded-xl bg-[#F7F4F1] p-3 text-xs leading-5 text-[#68625C]">
                  <DiagnosticDetails event={eventDetails[event.id] ?? event} loading={Boolean(detailLoading[event.id])} />
                  {event.level === 'error' ? <button type="button" onClick={() => setFeedbackEventId(event.id)} className="mt-2 block font-medium text-[#ED4D2D]"><I18nText>反馈此问题</I18nText></button> : null}
                </div>
              ) : null}
              <button type="button" onClick={() => void toggleEvent(event.id)} aria-expanded={expanded} className="mt-3 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-xl border border-[#DEDAD4] text-sm font-medium text-[#625D57] transition hover:bg-[#F6F3F0]">
                {expanded ? i18nAttribute("收起详情") : i18nAttribute("查看详情")}
                <ChevronDown size={16} className={expanded ? 'rotate-180 transition' : 'transition'} />
              </button>
            </article>
          );
        })}
      </div>

      <div data-testid="system-event-desktop-table" className="hidden overflow-hidden rounded-[22px] border border-[#DEDAD4] bg-white md:block">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="border-b border-[#E7E2DD] bg-[#F8F6F3] text-xs font-medium text-[#77716A]">
            <tr>
              <th className="w-[170px] px-4 py-3"><I18nText>时间</I18nText></th>
              <th className="w-[92px] px-3 py-3"><I18nText>级别</I18nText></th>
              <th className="w-[120px] px-3 py-3"><I18nText>来源</I18nText></th>
              <th className="px-3 py-3"><I18nText>摘要</I18nText></th>
              <th className="w-[70px] px-3 py-3 text-right"><I18nText>详情</I18nText></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#EEEAE6]">
            {!loading && events.length === 0 ? (
              <tr><td colSpan={5} className="px-5 py-12 text-center text-sm text-[#817B75]"><I18nText>当前筛选条件下暂无日志。</I18nText></td></tr>
            ) : null}
            {events.map((event) => {
              const expanded = expandedEventId === event.id;
              const summary = event.level === 'error' || event.metadata.diagnostics ? event.message : ignoredImportEventSummary(event, i18nAttribute) ?? i18nAttribute(event.message);
              return (
                <tr key={event.id} className="group align-top hover:bg-[#FCFAF8]">
                  <td className="px-4 py-3.5 tabular-nums text-[#716B64]">{new Date(event.createdAt).toLocaleString(locale)}</td>
                  <td className="px-3 py-3"><Badge tone={tone(event.level)}>{levelLabel(event.level)}</Badge></td>
                  <td className="px-3 py-3 text-[#5F5A54]">{sourceLabel(event.source)}</td>
                  <td className="px-3 py-3.5">
                    <div data-i18n-skip className="break-words font-medium leading-6 text-[#2A2825]">{summary}</div>
                    {expanded ? (
                      <div className="mt-3 rounded-xl bg-[#F7F4F1] p-3 text-xs leading-5 text-[#68625C]">
                        <DiagnosticDetails event={eventDetails[event.id] ?? event} loading={Boolean(detailLoading[event.id])} />
                        {event.level === 'error' ? <button type="button" onClick={() => setFeedbackEventId(event.id)} className="mt-2 block font-medium text-[#ED4D2D]"><I18nText>反馈此问题</I18nText></button> : null}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <button type="button" onClick={() => void toggleEvent(event.id)} aria-expanded={expanded} aria-label={expanded ? i18nAttribute("收起日志详情") : i18nAttribute("展开日志详情")} className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[#77716A] transition hover:bg-[#F2EEEA] hover:text-[#ED4D2D]">
                      <ChevronDown size={16} className={expanded ? 'rotate-180 transition' : 'transition'} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 text-sm text-[#77716A]">
        <span><I18nText>共 </I18nText>{total} <I18nText>条记录</I18nText></span>
        {totalPages > 1 ? (
          <div className="flex items-center gap-2">
            <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white disabled:opacity-40" aria-label={i18nAttribute("上一页")}><ChevronLeft size={16} /></button>
            <span className="min-w-14 text-center text-[#4F4A45]">{page} / {totalPages}</span>
            <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((current) => Math.min(totalPages, current + 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white disabled:opacity-40" aria-label={i18nAttribute("下一页")}><ChevronRight size={16} /></button>
          </div>
        ) : null}
      </footer>
      {feedbackEventId !== null ? <FeedbackDialog initialKind="issue" eventId={feedbackEventId || undefined} onClose={() => setFeedbackEventId(null)} /> : null}
    </div>
  );
}
