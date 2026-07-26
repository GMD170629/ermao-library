'use client';

import type {
  EventResponse,
  LogSettingsResponse,
  ManagementResponse
} from '@/generated/api-v2';
import { apiV2Request } from '@/lib/api-v2';

import { AlertTriangle, Database, HardDrive, RefreshCw, Settings2 } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Badge, type BadgeTone } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { PageTitle } from '../../components/ui/page-title';
import { useI18n } from '../../i18n/provider';
import { ManagementNav } from './management-nav';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type SystemEvent = {
  id: string;
  level: string;
  source: string;
  action: string;
  message: string;
  createdAt: string;
};

type OverviewData = {
  cards: Record<string, number>;
  checks: Record<string, { status: string; message: string }>;
  recentEvents: SystemEvent[];
};

function formatBytes(value: number) {
  if (!value) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function checkTone(status: string): BadgeTone {
  if (status === 'ok') return 'green';
  if (status === 'warn' || status === 'warning') return 'amber';
  if (status === 'error' || status === 'failed') return 'red';
  return 'slate';
}

function eventTone(level: string): BadgeTone {
  if (level === 'error') return 'red';
  if (level === 'warning' || level === 'warn') return 'amber';
  return 'slate';
}

export function ManagementOverviewPage() {
  const { t: i18nAttribute } = useAttributeI18n();
  const { locale } = useI18n();
  const [payload, setPayload] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function load() {
    setLoading(true);
    try {
      const [management, logSettings, events] = await Promise.all([
        apiV2Request<ManagementResponse>('/api/v2/reporting/management'),
        apiV2Request<LogSettingsResponse>('/api/v2/operations/log-settings'),
        apiV2Request<{ items: EventResponse[]; page: number; pageSize: number; total: number }>(
          '/api/v2/operations/events?pageSize=8'
        )
      ]);
      setPayload({
        cards: {
          failedImports: management.failedJobs,
          pendingOrganize: 0,
          eventLogSizeBytes: logSettings.sizeBytes,
          eventLogMaxBytes: logSettings.maxBytes
        },
        checks: {
          accounts: { status: 'ok', message: `${management.users}` },
          catalog: { status: 'ok', message: `${management.works}` },
          queues: {
            status: management.failedJobs ? 'warning' : 'ok',
            message: `${management.queuedImports + management.queuedDownloads + management.queuedDeliveries}`
          }
        },
        recentEvents: events.items.map((event) => ({
          id: event.id,
          level: event.severity,
          source: event.kind.split('.', 1)[0] || 'system',
          action: event.kind,
          message: event.messageKey,
          createdAt: event.createdAt
        }))
      });
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取管理概览失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const cards = payload?.cards ?? {};
  const logPercent = cards.eventLogMaxBytes ? Math.min(100, Math.round((cards.eventLogSizeBytes / cards.eventLogMaxBytes) * 100)) : 0;

  return (
    <div className="space-y-6">
      <PageTitle title={i18nAttribute("管理概览")} desc={i18nAttribute("集中查看异常、待处理项和系统运行状态。")} action={<Button variant="secondary" icon={RefreshCw} loading={loading} loadingText={i18nAttribute("刷新中")} onClick={() => void load()}><I18nText>刷新</I18nText></Button>} />
      <ManagementNav />
      {error ? <div className="rounded-2xl border border-red-100 bg-red-50 p-4 text-sm text-red-700">{error}</div> : null}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: '失败导入', value: cards.failedImports ?? 0, href: '/import-tasks', icon: AlertTriangle, tone: (cards.failedImports ?? 0) > 0 ? 'red' : 'green' },
          { label: '待整理作品', value: cards.pendingOrganize ?? 0, href: '/organize/pending', icon: Settings2, tone: (cards.pendingOrganize ?? 0) > 0 ? 'amber' : 'green' }
        ].map(({ label, value, href, icon: Icon, tone }) => (
          <Link key={label} href={href} className="rounded-[22px] border border-slate-200 bg-white p-5 shadow-sm transition hover:border-blue-100 hover:bg-blue-50/30">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm text-slate-500">{i18nAttribute(label)}</div>
              <Badge tone={tone as BadgeTone}><Icon size={13} className="mr-1" />{value > 0 ? i18nAttribute("需处理") : i18nAttribute("正常")}</Badge>
            </div>
            <div className="mt-3 text-3xl font-semibold text-slate-950">{value}</div>
          </Link>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
        <section className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2 font-semibold text-slate-900"><Database size={18} /><I18nText>系统检查</I18nText></div>
          <div className="mt-4 space-y-3">
            {Object.entries(payload?.checks ?? {}).map(([key, check]) => (
              <div key={key} className="flex items-start justify-between gap-3 rounded-2xl bg-slate-50 px-4 py-3">
                <div>
                  <div className="text-sm font-medium text-slate-900">{key}</div>
                  <div className="mt-1 text-sm text-slate-500">{check.message}</div>
                </div>
                <Badge tone={checkTone(check.status)}>{check.status}</Badge>
              </div>
            ))}
          </div>
          <div className="mt-5 rounded-2xl bg-slate-50 px-4 py-3">
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 font-medium text-slate-900"><HardDrive size={16} /><I18nText>结构化日志</I18nText></span>
              <span className="text-slate-500">{formatBytes(cards.eventLogSizeBytes ?? 0)} / {formatBytes(cards.eventLogMaxBytes ?? 5 * 1024 * 1024)}</span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
              <div className="h-full rounded-full bg-blue-600" style={{ width: `${logPercent}%` }} />
            </div>
          </div>
        </section>
        <section className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div className="font-semibold text-slate-900"><I18nText>最近事件</I18nText></div>
            <Link href="/management/logs" className="text-sm font-medium text-blue-700 hover:text-blue-800"><I18nText>查看全部</I18nText></Link>
          </div>
          <div className="mt-4 space-y-3">
            {(payload?.recentEvents ?? []).length === 0 ? <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-500"><I18nText>暂无结构化事件。</I18nText></div> : null}
            {(payload?.recentEvents ?? []).map((event) => (
              <div key={event.id} className="rounded-2xl bg-slate-50 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={eventTone(event.level)}>{event.level}</Badge>
                  <span className="text-sm font-medium text-slate-900">{i18nAttribute(event.message)}</span>
                </div>
                <div className="mt-2 text-xs text-slate-500">{event.source} · {event.action} · {new Date(event.createdAt).toLocaleString(locale)}</div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
