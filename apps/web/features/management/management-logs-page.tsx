'use client';

import { ChevronDown, ChevronLeft, ChevronRight, Download, HardDrive, RefreshCw, Save, Search, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { Badge, type BadgeTone } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useToast } from '../../components/ui/feedback';
import { PageTitle } from '../../components/ui/page-title';
import { useI18n } from '../../i18n/provider';
import { ManagementNav } from './management-nav';
import { ignoredImportEventSummary } from './system-event-presentation';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type SystemEvent = {
  id: string;
  level: string;
  source: string;
  actorType: string;
  action: string;
  targetType?: string | null;
  targetId?: string | null;
  message: string;
  metadata: Record<string, unknown>;
  createdAt: string;
};

type EventsData = {
  events: SystemEvent[];
  total: number;
  totalPages?: number;
  storage: { sizeBytes: number; maxBytes: number; lastPrunedAt?: string | null };
  facets: { sources: Array<{ source: string; count: number }>; levels: Array<{ level: string; count: number }> };
};

type EventsPayload = {
  ok: boolean;
  data?: EventsData;
  error?: { message: string };
};

function tone(level: string): BadgeTone {
  if (level === 'error') return 'red';
  if (level === 'warning' || level === 'warn') return 'amber';
  return 'slate';
}

function levelLabel(level: string) {
  return { info: '信息', warning: '警告', warn: '警告', error: '错误' }[level] ?? level;
}

function sourceLabel(source: string) {
  return { import: '导入', download: '下载', folder: '书库', kindle: 'Kindle', library: '书库', system: '系统' }[source] ?? source;
}

function targetHref(event: SystemEvent) {
  if (event.targetType === 'book' && event.targetId) return `/books/${event.targetId}`;
  if (event.targetType === 'kindleSendTask') return '/settings/email?tab=queue';
  if (event.targetType === 'importTask') return '/settings/library';
  if (event.targetType === 'library') return '/settings/library';
  return '';
}

function redactString(value: string) {
  return value
    .replace(/\/(?:Users|home|var|Volumes|volume\d+|mnt|srv|opt)\/[^\s"',}\]]+/gi, '[本地路径]')
    .replace(/[A-Z]:\\[^\s"',}\]]+/gi, '[本地路径]');
}

function sanitizeValue(value: unknown): unknown {
  if (typeof value === 'string') return redactString(value);
  if (Array.isArray(value)) return value.map(sanitizeValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, sanitizeValue(item)]));
  }
  return value;
}

function csvCell(value: unknown) {
  return `"${String(value ?? '').replaceAll('"', '""')}"`;
}

function localDateBoundary(value: string, nextDay = false) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day + (nextDay ? 1 : 0), 0, 0, 0, 0).toISOString();
}

export function ManagementLogsPage({ embedded = false }: { embedded?: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const { locale } = useI18n();
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const [source, setSource] = useState('');
  const [level, setLevel] = useState('');
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [expandedEventId, setExpandedEventId] = useState('');
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const [storage, setStorage] = useState<{ sizeBytes: number; maxBytes: number; lastPrunedAt?: string | null }>({ sizeBytes: 0, maxBytes: 5 * 1024 * 1024 });
  const [logMaxMb, setLogMaxMb] = useState(5);
  const [savingLimit, setSavingLimit] = useState(false);
  const toast = useToast();

  const buildParams = useCallback((targetPage: number, pageSize = 40) => {
    const params = new URLSearchParams({ page: String(targetPage), pageSize: String(pageSize) });
    if (source) params.set('source', source);
    if (level) params.set('level', level);
    if (appliedSearch) params.set('search', appliedSearch);
    if (dateFrom) params.set('dateFrom', localDateBoundary(dateFrom));
    if (dateTo) params.set('dateTo', localDateBoundary(dateTo, true));
    return params;
  }, [appliedSearch, dateFrom, dateTo, level, source]);

  const load = useCallback(async () => {
    if (dateFrom && dateTo && dateFrom > dateTo) {
      setError('开始日期不能晚于结束日期');
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(`/api/management/events?${buildParams(page).toString()}`);
      const payload = (await response.json()) as EventsPayload;
      if (!payload.ok) throw new Error(payload.error?.message ?? '读取日志失败');
      setEvents(payload.data?.events ?? []);
      setTotal(payload.data?.total ?? 0);
      setTotalPages(Math.max(1, Number(payload.data?.totalPages ?? 1)));
      if (payload.data?.storage) {
        setStorage(payload.data.storage);
        setLogMaxMb(Math.round(payload.data.storage.maxBytes / 1024 / 1024));
      }
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取日志失败');
    } finally {
      setLoading(false);
    }
  }, [buildParams, dateFrom, dateTo, page]);

  async function clearLogs() {
    if (!window.confirm(i18nAttribute('清理信息和警告日志？错误与关键审计事件会保留。'))) return;
    const response = await fetch('/api/management/events', { method: 'DELETE' });
    const payload = await response.json().catch(() => null) as { ok?: boolean; data?: { deleted: number }; error?: { message: string } } | null;
    if (!payload?.ok) {
      toast.error('清理日志失败', payload?.error?.message ?? '请稍后重试');
      return;
    }
    toast.success(`已清理 ${payload.data?.deleted ?? 0} 条日志`);
    if (page === 1) await load();
    else setPage(1);
  }

  async function saveLogLimit() {
    if (!Number.isInteger(logMaxMb) || logMaxMb < 1 || logMaxMb > 100) {
      toast.error('日志容量设置无效', '容量上限必须在 1 MB 到 100 MB 之间');
      return;
    }
    const nextBytes = logMaxMb * 1024 * 1024;
    if (nextBytes < storage.maxBytes && !window.confirm(i18nAttribute('降低容量上限会立即删除最旧日志，是否继续？'))) return;
    setSavingLimit(true);
    try {
      const response = await fetch('/api/system/log-settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ maxBytes: nextBytes })
      });
      const payload = await response.json() as { ok?: boolean; data?: { storage?: typeof storage }; error?: { message?: string } };
      if (!payload.ok || !payload.data?.storage) throw new Error(payload.error?.message ?? '保存日志容量失败');
      setStorage(payload.data.storage);
      toast.success('日志容量上限已保存');
      await load();
    } catch (reason) {
      toast.error('保存日志容量失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setSavingLimit(false);
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
      const exported: SystemEvent[] = [];
      let exportPage = 1;
      let exportPages = 1;
      do {
        const response = await fetch(`/api/management/events?${buildParams(exportPage, 100).toString()}`);
        const payload = (await response.json()) as EventsPayload;
        if (!payload.ok) throw new Error(payload.error?.message ?? '导出日志失败');
        exported.push(...(payload.data?.events ?? []));
        exportPages = Math.max(1, Number(payload.data?.totalPages ?? 1));
        exportPage += 1;
      } while (exportPage <= exportPages);

      const rows = [
        ['时间', '级别', '来源', '摘要', '动作', '关联类型'].map(csvCell).join(','),
        ...exported.map((event) => [
          new Date(event.createdAt).toLocaleString(locale),
          levelLabel(event.level),
          sourceLabel(event.source),
          ignoredImportEventSummary(event, i18nAttribute) ?? redactString(event.message),
          event.action,
          event.targetType ?? ''
        ].map(csvCell).join(','))
      ];
      const blob = new Blob([`\uFEFF${rows.join('\n')}`], { type: 'text/csv;charset=utf-8' });
      const href = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = href;
      link.download = `shuku-system-logs-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(href);
      toast.success(`已导出 ${exported.length} 条日志`);
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
      {!embedded ? <PageTitle title={i18nAttribute("系统日志")} desc={i18nAttribute("按级别、来源、日期和关键字查看系统事件。")} action={<Button variant="secondary" icon={RefreshCw} loading={loading} loadingText={i18nAttribute("刷新中")} onClick={() => void load()}><I18nText>刷新</I18nText></Button>} /> : null}
      {!embedded ? <ManagementNav /> : null}

      <section className="rounded-[22px] border border-[#DEDAD4] bg-white p-4 sm:p-5" aria-labelledby="log-storage-title">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <HardDrive size={20} className="mt-0.5 text-[#ED4D2D]" />
            <div>
              <h2 id="log-storage-title" className="font-semibold text-[#2A2825]"><I18nText>日志容量管理</I18nText></h2>
              <p className="mt-1 text-sm leading-6 text-[#77716A]">
                {i18nAttribute('当前使用 {used} MB / {max} MB', {
                  used: (storage.sizeBytes / 1024 / 1024).toLocaleString(locale, { maximumFractionDigits: 2 }),
                  max: (storage.maxBytes / 1024 / 1024).toLocaleString(locale, { maximumFractionDigits: 0 })
                })}
              </p>
              <p className="text-xs text-[#918A83]">
                {storage.lastPrunedAt
                  ? i18nAttribute('上次自动清理：{time}', { time: new Date(storage.lastPrunedAt).toLocaleString(locale) })
                  : i18nAttribute('尚未执行自动清理')}
              </p>
            </div>
          </div>
          <div className="flex items-end gap-2">
            <label className="text-xs text-[#716B64]">
              <I18nText>容量上限（MB）</I18nText>
              <input
                type="number"
                min={1}
                max={100}
                step={1}
                value={logMaxMb}
                onChange={(event) => setLogMaxMb(Number(event.target.value))}
                className="mt-1 h-10 w-28 rounded-xl border border-[#DEDAD4] px-3 text-sm text-[#2A2825] outline-none focus:border-[#F0A28F] focus:ring-2 focus:ring-[#FAD9D0]"
              />
            </label>
            <Button variant="secondary" icon={Save} loading={savingLimit} loadingText={i18nAttribute("保存中")} onClick={() => void saveLogLimit()}><I18nText>保存</I18nText></Button>
          </div>
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-[#EEEAE6]">
          <div className="h-full rounded-full bg-[#ED6A4F]" style={{ width: `${Math.min(100, storage.maxBytes ? storage.sizeBytes / storage.maxBytes * 100 : 0)}%` }} />
        </div>
      </section>

      <section className="rounded-[22px] border border-[#DEDAD4] bg-white p-4" aria-label={i18nAttribute("日志筛选")}>
        <div className="flex flex-wrap gap-2">
          {['', 'info', 'warning', 'error'].map((item) => (
            <button key={item || 'all-level'} type="button" onClick={() => { setLevel(item); setPage(1); }} className={`min-h-9 rounded-xl border px-3 text-sm ${level === item ? 'border-[#F4B7A8] bg-[#FCE5DE] text-[#ED4D2D]' : 'border-[#DEDAD4] text-[#625D57] hover:bg-[#F6F3F0]'}`}>{item ? levelLabel(item) : i18nAttribute("全部级别")}</button>
          ))}
          <span className="mx-1 hidden h-9 w-px bg-[#DEDAD4] sm:block" />
          {['', 'import', 'download', 'folder', 'library', 'system'].map((item) => (
            <button key={item || 'all-source'} type="button" onClick={() => { setSource(item); setPage(1); }} className={`min-h-9 rounded-xl border px-3 text-sm ${source === item ? 'border-[#F4B7A8] bg-[#FCE5DE] text-[#ED4D2D]' : 'border-[#DEDAD4] text-[#625D57] hover:bg-[#F6F3F0]'}`}>{item ? sourceLabel(item) : i18nAttribute("全部来源")}</button>
          ))}
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[150px_150px_minmax(0,1fr)] lg:items-end">
          <label className="text-xs text-[#716B64]">
            <I18nText>开始日期</I18nText><input type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setPage(1); }} className="mt-1 h-10 w-full rounded-xl border border-[#DEDAD4] bg-white px-3 text-sm text-[#2A2825] outline-none focus:border-[#F0A28F] focus:ring-2 focus:ring-[#FAD9D0]" />
          </label>
          <label className="text-xs text-[#716B64]">
            <I18nText>结束日期</I18nText><input type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setPage(1); }} className="mt-1 h-10 w-full rounded-xl border border-[#DEDAD4] bg-white px-3 text-sm text-[#2A2825] outline-none focus:border-[#F0A28F] focus:ring-2 focus:ring-[#FAD9D0]" />
          </label>
          <label className="text-xs text-[#716B64]">
            <I18nText>关键字</I18nText><span className="mt-1 flex h-10 items-center gap-2 rounded-xl border border-[#DEDAD4] px-3 focus-within:border-[#F0A28F] focus-within:ring-2 focus-within:ring-[#FAD9D0]">
              <Search size={15} className="text-[#958F88]" />
              <input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') applySearch(); }} className="min-w-0 flex-1 bg-transparent text-sm text-[#2A2825] outline-none" placeholder={i18nAttribute("搜索摘要、动作或关联对象")} />
            </span>
          </label>
          <div className="flex flex-wrap justify-end gap-2 lg:col-span-3">
            <Button variant="secondary" icon={Search} className="whitespace-nowrap" onClick={applySearch}><I18nText>搜索</I18nText></Button>
            <Button variant="secondary" icon={RefreshCw} loading={loading} loadingText={i18nAttribute("刷新中")} className="whitespace-nowrap" onClick={() => void load()}><I18nText>刷新</I18nText></Button>
            <Button variant="secondary" icon={Download} loading={exporting} loadingText={i18nAttribute("导出中")} className="whitespace-nowrap" onClick={() => void exportLogs()}><I18nText>导出</I18nText></Button>
            <Button variant="ghost" icon={Trash2} className="whitespace-nowrap" onClick={() => void clearLogs()}><I18nText>清理</I18nText></Button>
          </div>
        </div>
      </section>

      {error ? <div className="rounded-2xl border border-red-100 bg-red-50 p-4 text-sm text-red-700">{error}</div> : null}

      <div className="space-y-3 md:hidden">
        {!loading && events.length === 0 ? <div className="rounded-[22px] border border-[#DEDAD4] bg-white px-5 py-10 text-center text-sm text-[#817B75]"><I18nText>当前筛选条件下暂无日志。</I18nText></div> : null}
        {events.map((event) => {
          const href = targetHref(event);
          const expanded = expandedEventId === event.id;
          const safeMetadata = sanitizeValue(event.metadata);
          const summary = ignoredImportEventSummary(event, i18nAttribute) ?? i18nAttribute(redactString(event.message));
          return (
            <article key={event.id} data-testid="system-event-mobile-card" className="rounded-[22px] border border-[#DEDAD4] bg-white p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={tone(event.level)}>{levelLabel(event.level)}</Badge>
                <Badge tone="slate">{sourceLabel(event.source)}</Badge>
                <time className="text-xs tabular-nums text-[#77716A]">{new Date(event.createdAt).toLocaleString(locale)}</time>
              </div>
              <p className="mt-3 break-words text-sm font-medium leading-6 text-[#2A2825]">{summary}</p>
              {expanded ? (
                <div className="mt-3 rounded-xl bg-[#F7F4F1] p-3 text-xs leading-5 text-[#68625C]">
                  <div><span className="text-[#969089]"><I18nText>动作：</I18nText></span>{event.action || '—'}</div>
                  <div><span className="text-[#969089]"><I18nText>执行者：</I18nText></span>{event.actorType || 'system'}</div>
                  {event.targetType ? <div><span className="text-[#969089]"><I18nText>关联：</I18nText></span>{event.targetType}{event.targetId ? ` · ${event.targetId}` : ''}</div> : null}
                  {Object.keys(event.metadata ?? {}).length > 0 ? <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-white p-2 text-[11px] text-[#716B64]">{JSON.stringify(safeMetadata, null, 2)}</pre> : null}
                  {href ? <Link href={href} className="mt-2 inline-flex font-medium text-[#ED4D2D] hover:text-[#C83B23]"><I18nText>打开关联对象</I18nText></Link> : null}
                </div>
              ) : null}
              <button type="button" onClick={() => setExpandedEventId(expanded ? '' : event.id)} aria-expanded={expanded} className="mt-3 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-xl border border-[#DEDAD4] text-sm font-medium text-[#625D57] transition hover:bg-[#F6F3F0]">
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
              const href = targetHref(event);
              const expanded = expandedEventId === event.id;
              const safeMetadata = sanitizeValue(event.metadata);
              const summary = ignoredImportEventSummary(event, i18nAttribute) ?? i18nAttribute(redactString(event.message));
              return (
                <tr key={event.id} className="group align-top hover:bg-[#FCFAF8]">
                  <td className="px-4 py-3.5 tabular-nums text-[#716B64]">{new Date(event.createdAt).toLocaleString(locale)}</td>
                  <td className="px-3 py-3"><Badge tone={tone(event.level)}>{levelLabel(event.level)}</Badge></td>
                  <td className="px-3 py-3 text-[#5F5A54]">{sourceLabel(event.source)}</td>
                  <td className="px-3 py-3.5">
                    <div className="break-words font-medium leading-6 text-[#2A2825]">{summary}</div>
                    {expanded ? (
                      <div className="mt-3 rounded-xl bg-[#F7F4F1] p-3 text-xs leading-5 text-[#68625C]">
                        <div><span className="text-[#969089]"><I18nText>动作：</I18nText></span>{event.action || '—'}</div>
                        <div><span className="text-[#969089]"><I18nText>执行者：</I18nText></span>{event.actorType || 'system'}</div>
                        {event.targetType ? <div><span className="text-[#969089]"><I18nText>关联：</I18nText></span>{event.targetType}{event.targetId ? ` · ${event.targetId}` : ''}</div> : null}
                        {Object.keys(event.metadata ?? {}).length > 0 ? <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-white p-2 text-[11px] text-[#716B64]">{JSON.stringify(safeMetadata, null, 2)}</pre> : null}
                        {href ? <Link href={href} className="mt-2 inline-flex font-medium text-[#ED4D2D] hover:text-[#C83B23]"><I18nText>打开关联对象</I18nText></Link> : null}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <button type="button" onClick={() => setExpandedEventId(expanded ? '' : event.id)} aria-expanded={expanded} aria-label={expanded ? i18nAttribute("收起日志详情") : i18nAttribute("展开日志详情")} className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[#77716A] transition hover:bg-[#F2EEEA] hover:text-[#ED4D2D]">
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
    </div>
  );
}
