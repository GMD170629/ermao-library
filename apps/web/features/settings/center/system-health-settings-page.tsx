'use client';

import { Activity, AlertTriangle, CheckCircle2, Circle, LoaderCircle, RefreshCw, SkipForward, XCircle } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/feedback';
import { I18nText, useI18n } from '@/i18n/provider';
import { healthRunElapsedMs } from './health-run-time';
import { SettingsCenterShell } from './settings-center-shell';

type CheckStatus = 'pending' | 'running' | 'ok' | 'warning' | 'error' | 'skipped';
type HealthItem = {
  id: string;
  group: string;
  labelCode: string;
  status: CheckStatus;
  messageCode: string;
  details: Record<string, unknown>;
  startedAt?: number | null;
  finishedAt?: number | null;
  durationMs?: number | null;
};
type HealthRun = {
  runId: string;
  status: 'running' | 'completed' | 'warning' | 'error' | 'failed';
  version: number;
  startedAt: number;
  finishedAt?: number | null;
  groups: Array<{ id: string; labelCode: string }>;
  items: HealthItem[];
  summary: { total: number; completed: number; ok: number; warning: number; error: number; skipped: number };
};
type RunPayload = { ok?: boolean; data?: { run?: HealthRun; created?: boolean }; error?: { message?: string } };

const LABELS: Record<string, string> = {
  'health.group.storage': '目录与数据库',
  'health.group.queues': '后台队列',
  'health.group.configuration': '功能配置',
  'health.item.database': '数据库连接',
  'health.item.importFolder': '启用的导入目录',
  'health.item.storageRoot': '存储根目录',
  'health.item.databaseDirectory': '数据库目录',
  'health.item.libraryDirectory': '书库目录',
  'health.item.coversDirectory': '封面目录',
  'health.item.indexesDirectory': '索引目录',
  'health.item.backupsDirectory': '备份目录',
  'health.item.logsDirectory': '日志目录',
  'health.item.secretsDirectory': '密钥目录',
  'health.item.importQueue': '导入队列',
  'health.item.downloadQueue': '下载队列',
  'health.item.kindleQueue': 'Kindle 发送队列',
  'health.item.metadataQueue': '元数据识别队列',
  'health.item.smtp': 'Kindle / SMTP 配置',
  'health.item.metadataProviders': '元数据数据源'
};

const MESSAGES: Record<string, string> = {
  'health.pending': '等待检查',
  'health.running': '正在检查',
  'health.directory.ok': '目录权限正常',
  'health.directory.notConfigured': '目录尚未配置',
  'health.directory.missing': '目录不存在',
  'health.directory.notDirectory': '配置路径不是目录',
  'health.directory.notReadable': '目录不可读取或遍历',
  'health.directory.notWritable': '目录不可写入',
  'health.database.ok': '数据库连接正常',
  'health.database.error': '数据库连接失败',
  'health.queue.disabled': '队列已停用',
  'health.queue.noHeartbeat': '未收到队列运行心跳',
  'health.queue.stale': '队列心跳已过期',
  'health.queue.recentError': '队列运行中，但最近出现错误',
  'health.queue.ok': '队列运行正常',
  'health.smtp.invalid': 'SMTP 配置无效',
  'health.smtp.notConfigured': 'SMTP 尚未配置',
  'health.smtp.connectionFailed': 'SMTP 连接或认证失败',
  'health.smtp.noRecipients': 'SMTP 正常，但尚无用户配置 Kindle 邮箱',
  'health.smtp.ok': 'SMTP 连接、加密与认证正常',
  'health.providers.noneEnabled': '尚未启用元数据数据源',
  'health.providers.failed': '一个或多个数据源连接失败',
  'health.providers.ok': '已启用的数据源连接正常',
  'health.check.failed': '检查执行失败',
  'health.run.interrupted': '服务中断，检查未能完成',
  'health.unknownCheck': '未知检查项目'
};

function statusLabel(status: CheckStatus) {
  return {
    pending: '等待中',
    running: '检查中',
    ok: '正常',
    warning: '警告',
    error: '错误',
    skipped: '已跳过'
  }[status];
}

function statusVisual(status: CheckStatus) {
  if (status === 'running') return { Icon: LoaderCircle, color: 'text-blue-600', bg: 'bg-blue-50 border-blue-100', spin: true };
  if (status === 'ok') return { Icon: CheckCircle2, color: 'text-emerald-600', bg: 'bg-emerald-50 border-emerald-100', spin: false };
  if (status === 'warning') return { Icon: AlertTriangle, color: 'text-amber-600', bg: 'bg-amber-50 border-amber-100', spin: false };
  if (status === 'error') return { Icon: XCircle, color: 'text-red-600', bg: 'bg-red-50 border-red-100', spin: false };
  if (status === 'skipped') return { Icon: SkipForward, color: 'text-slate-500', bg: 'bg-slate-50 border-slate-200', spin: false };
  return { Icon: Circle, color: 'text-[#AAA39B]', bg: 'bg-white border-[#E4DFDA]', spin: false };
}

function terminal(run: HealthRun | null) {
  return Boolean(run && run.status !== 'running' && run.summary.completed === run.summary.total);
}

export function SystemHealthSettingsPage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const [run, setRun] = useState<HealthRun | null>(null);
  const [starting, setStarting] = useState(false);
  const [streamMode, setStreamMode] = useState<'idle' | 'sse' | 'polling'>('idle');
  const [now, setNow] = useState(Date.now());
  const sourceRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const errorsRef = useRef(0);
  const allowNavigationRef = useRef(false);

  const applySnapshot = useCallback((next: HealthRun) => {
    setRun((current) => !current || next.version >= current.version ? next : current);
    sessionStorage.setItem('shuku.activeHealthRunId', next.runId);
    if (terminal(next)) {
      sessionStorage.removeItem('shuku.activeHealthRunId');
      sourceRef.current?.close();
      sourceRef.current = null;
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      setStreamMode('idle');
    }
  }, []);

  const loadSnapshot = useCallback(async (runId: string) => {
    const response = await fetch(`/api/system/health/runs/${encodeURIComponent(runId)}`, { cache: 'no-store' });
    const payload = await response.json() as RunPayload;
    if (!payload.ok || !payload.data?.run) throw new Error(payload.error?.message ?? t('读取健康检查状态失败'));
    applySnapshot(payload.data.run);
    return payload.data.run;
  }, [applySnapshot, t]);

  const startPolling = useCallback((runId: string) => {
    sourceRef.current?.close();
    sourceRef.current = null;
    if (pollRef.current) clearInterval(pollRef.current);
    setStreamMode('polling');
    pollRef.current = setInterval(() => {
      void loadSnapshot(runId).catch(() => undefined);
    }, 1000);
  }, [loadSnapshot]);

  const subscribe = useCallback((runId: string, after = 0) => {
    sourceRef.current?.close();
    errorsRef.current = 0;
    setStreamMode('sse');
    const source = new EventSource(`/api/system/health/runs/${encodeURIComponent(runId)}/events?after=${after}`);
    sourceRef.current = source;
    const receive = (event: Event) => {
      errorsRef.current = 0;
      const message = event as MessageEvent<string>;
      const payload = JSON.parse(message.data) as { run: HealthRun };
      applySnapshot(payload.run);
    };
    ['run.started', 'check.started', 'check.updated', 'run.completed', 'run.failed'].forEach((name) => source.addEventListener(name, receive));
    source.onerror = () => {
      errorsRef.current += 1;
      if (errorsRef.current >= 3) startPolling(runId);
    };
  }, [applySnapshot, startPolling]);

  useEffect(() => {
    const activeRunId = sessionStorage.getItem('shuku.activeHealthRunId');
    if (activeRunId) {
      void loadSnapshot(activeRunId)
        .then((snapshot) => { if (!terminal(snapshot)) subscribe(snapshot.runId, snapshot.version); })
        .catch(() => sessionStorage.removeItem('shuku.activeHealthRunId'));
    }
    return () => {
      sourceRef.current?.close();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadSnapshot, subscribe]);

  useEffect(() => {
    if (!run || terminal(run)) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [run]);

  useEffect(() => {
    if (!run || terminal(run)) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    const interceptLinks = (event: MouseEvent) => {
      if (allowNavigationRef.current || event.defaultPrevented || event.button !== 0) return;
      const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href]') : null;
      if (!target || target.target === '_blank' || target.href === window.location.href) return;
      if (!window.confirm(t('健康检查仍在运行，离开后检查会继续。是否离开？'))) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      allowNavigationRef.current = true;
    };
    document.addEventListener('click', interceptLinks, true);
    return () => {
      window.removeEventListener('beforeunload', warn);
      document.removeEventListener('click', interceptLinks, true);
    };
  }, [run, t]);

  async function execute() {
    setStarting(true);
    try {
      const response = await fetch('/api/system/health/runs', { method: 'POST' });
      const payload = await response.json() as RunPayload;
      if (!payload.ok || !payload.data?.run) throw new Error(payload.error?.message ?? t('启动健康检查失败'));
      applySnapshot(payload.data.run);
      subscribe(payload.data.run.runId, 0);
    } catch (reason) {
      toast.error('启动健康检查失败', reason instanceof Error ? reason.message : t('请稍后重试'));
    } finally {
      setStarting(false);
    }
  }

  const elapsed = run ? healthRunElapsedMs(run.startedAt, run.finishedAt, now) : 0;
  const current = run?.items.find((item) => item.status === 'running');
  const groups = useMemo(() => run?.groups ?? [
    { id: 'storage', labelCode: 'health.group.storage' },
    { id: 'queues', labelCode: 'health.group.queues' },
    { id: 'configuration', labelCode: 'health.group.configuration' }
  ], [run]);
  const isRunning = Boolean(run && !terminal(run));

  return (
    <SettingsCenterShell title={t('系统健康检查')} description={t('手动检查运行目录、后台队列和关键功能配置，并实时查看每一项结果。')}>
      <section className="rounded-[22px] border border-[#DEDAD4] bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-lg font-semibold text-[#2A2825]">
              <Activity size={21} className="text-[#ED4D2D]" />
              <I18nText>运行状态</I18nText>
            </div>
            <p className="mt-1 text-sm leading-6 text-[#77716A]">
              {run
                ? t('已完成 {completed} / {total} 项 · 用时 {seconds} 秒', { completed: run.summary.completed, total: run.summary.total, seconds: Math.round(elapsed / 1000) })
                : t('健康检查只会在你手动执行时运行。')}
            </p>
            {current ? <p aria-live="polite" className="mt-1 text-sm font-medium text-blue-700">{t('正在检查：{item}', { item: t(LABELS[current.labelCode] ?? current.labelCode) })}</p> : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button icon={RefreshCw} loading={starting || isRunning} loadingText={isRunning ? t('检查中') : t('启动中')} onClick={() => void execute()} disabled={isRunning}>
              <I18nText>运行健康检查</I18nText>
            </Button>
          </div>
        </div>
        {run ? (
          <>
            <div className="mt-5 h-2 overflow-hidden rounded-full bg-[#EEEAE6]">
              <div className="h-full rounded-full bg-[#ED6A4F] transition-[width] duration-300" style={{ width: `${run.summary.total ? run.summary.completed / run.summary.total * 100 : 0}%` }} />
            </div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#716B64]">
              <span>{t('正常 {count}', { count: run.summary.ok })}</span>
              <span>{t('警告 {count}', { count: run.summary.warning })}</span>
              <span>{t('错误 {count}', { count: run.summary.error })}</span>
              <span>{t('跳过 {count}', { count: run.summary.skipped })}</span>
              {isRunning ? <span>{streamMode === 'polling' ? t('正在轮询恢复状态') : t('实时连接中')}</span> : null}
            </div>
          </>
        ) : null}
      </section>

      <div className="mt-6 space-y-5">
        {groups.map((group) => {
          const items = run?.items.filter((item) => item.group === group.id) ?? [];
          return (
            <section key={group.id} className="rounded-[22px] border border-[#DEDAD4] bg-white p-4 sm:p-5" aria-labelledby={`health-group-${group.id}`}>
              <h2 id={`health-group-${group.id}`} className="text-base font-semibold text-[#2A2825]">{t(LABELS[group.labelCode] ?? group.labelCode)}</h2>
              {!run ? <p className="mt-3 text-sm text-[#817B75]"><I18nText>执行后将在此实时显示检查项目。</I18nText></p> : null}
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                {items.map((item) => {
                  const visual = statusVisual(item.status);
                  const detailEntries = Object.entries(item.details ?? {}).filter(([, value]) => value !== null && value !== undefined && value !== '');
                  return (
                    <article key={item.id} className={`rounded-2xl border p-4 ${visual.bg}`}>
                      <div className="flex items-start gap-3">
                        <visual.Icon size={20} className={`mt-0.5 shrink-0 ${visual.color} ${visual.spin ? 'animate-spin' : ''}`} />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <h3 className="font-medium text-[#2A2825]">{t(LABELS[item.labelCode] ?? item.labelCode)}</h3>
                            <span className={`text-xs font-semibold ${visual.color}`}>{t(statusLabel(item.status))}</span>
                          </div>
                          <p className="mt-1 text-sm leading-6 text-[#68625C]">{t(MESSAGES[item.messageCode] ?? item.messageCode)}</p>
                          {item.durationMs !== null && item.durationMs !== undefined ? <p className="mt-1 text-xs text-[#918A83]">{t('耗时 {seconds} 秒', { seconds: Math.max(0.01, item.durationMs / 1000).toLocaleString(locale, { maximumFractionDigits: 2 }) })}</p> : null}
                          {detailEntries.length ? (
                            <details className="mt-2 text-xs text-[#716B64]">
                              <summary className="cursor-pointer font-medium"><I18nText>查看运行明细</I18nText></summary>
                              <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-white/80 p-3">{JSON.stringify(item.details, null, 2)}</pre>
                            </details>
                          ) : null}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </SettingsCenterShell>
  );
}
