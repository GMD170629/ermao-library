'use client';

import { apiV2Request } from '@/lib/api-v2';

import { AlertTriangle, Ban, Clock3, Mail, RefreshCw, RotateCcw, Send, Server } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, type BadgeTone } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useToast } from '../../components/ui/feedback';
import { useI18n } from '../../i18n/provider';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

export type KindleSendTask = {
  id: string;
  fileId: string;
  subject: string;
  recipientEmail: string;
  status: 'queued' | 'sending' | 'sent' | 'failed' | 'cancelled' | 'unknown';
  attemptCount: number;
  nextAttemptAt: string;
  errorCode: string | null;
  createdAt: string;
  updatedAt: string;
  canCancel: boolean;
  canRetry: boolean;
};

type DeliveryJobResource = {
  id: string;
  fileId: string;
  kind: string;
  recipient: string;
  subject: string;
  status: string;
  attempt: number;
  nextAttemptAt: string;
  errorCode: string | null;
  createdAt: string;
  updatedAt: string;
};

type JobPage = {
  items: DeliveryJobResource[];
  page: number;
  pageSize: number;
  total: number;
};

const statusOrder: KindleSendTask['status'][] = ['sending', 'queued', 'failed', 'unknown', 'sent', 'cancelled'];
const statusLabels: Record<KindleSendTask['status'], string> = {
  queued: '等待发送',
  sending: '发送中',
  sent: '已提交',
  failed: '发送失败',
  cancelled: '已取消',
  unknown: '结果未知'
};

function statusTone(status: KindleSendTask['status']): BadgeTone {
  if (status === 'sent') return 'green';
  if (status === 'failed') return 'red';
  if (status === 'unknown' || status === 'cancelled') return 'amber';
  return status === 'sending' ? 'blue' : 'slate';
}

function dateLabel(value: string | null, locale: string) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale);
}

function taskStatus(value: string): KindleSendTask['status'] {
  if (value === 'running') return 'sending';
  if (value === 'completed') return 'sent';
  if (value === 'queued' || value === 'retry') return 'queued';
  if (value === 'failed' || value === 'cancelled') return value;
  return 'unknown';
}

function toTask(job: DeliveryJobResource): KindleSendTask {
  const status = taskStatus(job.status);
  return {
    id: job.id,
    fileId: job.fileId,
    subject: job.subject,
    recipientEmail: job.recipient,
    status,
    attemptCount: job.attempt,
    nextAttemptAt: job.nextAttemptAt,
    errorCode: job.errorCode,
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
    canCancel: status === 'queued' || status === 'sending',
    canRetry: status === 'failed' || status === 'cancelled'
  };
}

export function KindleSendQueuePage({ embedded = false }: { embedded?: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const { locale } = useI18n();
  const toast = useToast();
  const [tasks, setTasks] = useState<KindleSendTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const loadTasks = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const page = await apiV2Request<JobPage>(
        '/api/v2/delivery/kindle/jobs?pageSize=200',
        { cache: 'no-store' }
      );
      setTasks(page.items.map(toTask));
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取发送队列失败');
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTasks();
    const timer = window.setInterval(() => void loadTasks(true), 8_000);
    return () => window.clearInterval(timer);
  }, [loadTasks]);

  const groups = useMemo(() => statusOrder.map((status) => ({
    status,
    tasks: tasks.filter((task) => task.status === status)
  })).filter((group) => group.tasks.length > 0), [tasks]);

  async function mutate(task: KindleSendTask, action: 'cancel' | 'retry') {
    setBusy(`${action}:${task.id}`);
    try {
      await apiV2Request<void>(
        action === 'cancel'
          ? `/api/v2/delivery/kindle/jobs/${task.id}`
          : `/api/v2/delivery/kindle/jobs/${task.id}/retry`,
        { method: action === 'cancel' ? 'DELETE' : 'POST' }
      );
      toast.success(action === 'cancel' ? '已取消发送' : '已重新排队');
      await loadTasks(true);
    } catch (reason) {
      toast.error('操作失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
    }
  }

  return (
    <div className={embedded ? '' : 'mx-auto max-w-6xl'}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-xl font-semibold text-[#242220]"><I18nText>Kindle 发送队列</I18nText></h3>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[#77716A]"><I18nText>“已提交”表示 SMTP 服务器已接收邮件，Kindle 的最终处理结果仍以 Amazon 通知为准。</I18nText></p>
        </div>
        <Button variant="secondary" icon={RefreshCw} loading={loading} loadingText={i18nAttribute("刷新中")} onClick={() => void loadTasks()}><I18nText>刷新</I18nText></Button>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {statusOrder.map((status) => {
          const count = tasks.filter((task) => task.status === status).length;
          return count > 0 ? <Badge key={status} tone={statusTone(status)}>{statusLabels[status]} {count}</Badge> : null;
        })}
      </div>

      {error ? <div className="mt-5 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
      {!loading && tasks.length === 0 ? (
        <div className="mt-6 rounded-[24px] border border-dashed border-[#D8D3CC] bg-white px-6 py-12 text-center">
          <Mail className="mx-auto text-[#A49D95]" size={28} />
          <p className="mt-3 font-medium text-[#3A3733]"><I18nText>还没有 Kindle 发送任务</I18nText></p>
          <p className="mt-1 text-sm text-[#817A73]"><I18nText>可以在图书详情的“更多操作”中选择“发送到 Kindle”。</I18nText></p>
        </div>
      ) : null}

      <div className="mt-6 space-y-8">
        {groups.map((group) => (
          <section key={group.status}>
            <div className="mb-3 flex items-center gap-2">
              <h4 className="font-semibold text-[#35322E]">{statusLabels[group.status]}</h4>
              <Badge tone={statusTone(group.status)}>{group.tasks.length}</Badge>
            </div>
            <div className="space-y-3">
              {group.tasks.map((task) => (
                <article key={task.id} className="rounded-[24px] border border-[#E3DED8] bg-white p-5 shadow-sm shadow-stone-900/[0.03]">
                  <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        {task.status === 'sending' ? <Send size={18} className="text-[#ED4D2D]" /> : <Mail size={18} className="text-[#766F68]" />}
                        <h5 className="break-words font-semibold text-[#242220]">{task.subject}</h5>
                        <Badge tone={statusTone(task.status)}>{statusLabels[task.status]}</Badge>
                        <Badge>Kindle</Badge>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-[#6F6962]">
                        <span className="rounded-full bg-[#F3F0EC] px-2.5 py-1"><I18nText>文件</I18nText> {task.fileId}</span>
                        <span className="rounded-full bg-[#F3F0EC] px-2.5 py-1"><I18nText>尝试 </I18nText>{task.attemptCount} <I18nText>次</I18nText></span>
                      </div>
                      <dl className="mt-4 grid gap-3 rounded-2xl bg-[#F8F6F3] p-4 text-xs text-[#655F58] sm:grid-cols-2 xl:grid-cols-3">
                        <div><dt className="text-[#9A938B]"><I18nText>收件邮箱</I18nText></dt><dd className="mt-1 break-all font-medium text-[#433F3B]">{task.recipientEmail}</dd></div>
                        <div><dt className="text-[#9A938B]"><I18nText>创建时间</I18nText></dt><dd className="mt-1 font-medium text-[#433F3B]">{dateLabel(task.createdAt, locale)}</dd></div>
                        <div><dt className="text-[#9A938B]"><I18nText>更新时间</I18nText></dt><dd className="mt-1 font-medium text-[#433F3B]">{dateLabel(task.updatedAt, locale)}</dd></div>
                      </dl>
                      {task.status === 'queued' ? <div className="mt-3 flex items-center gap-2 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-700"><Clock3 size={16} /><I18nText>下次尝试：</I18nText>{dateLabel(task.nextAttemptAt, locale)}</div> : null}
                      {task.errorCode ? <div className="mt-3 flex gap-2 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><span className="break-words">{task.errorCode}</span></div> : null}
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      {task.canCancel ? <Button variant="secondary" icon={Ban} loading={busy === `cancel:${task.id}`} loadingText={i18nAttribute("取消中")} onClick={() => void mutate(task, 'cancel')}><I18nText>取消</I18nText></Button> : null}
                      {task.canRetry ? <Button variant="secondary" icon={RotateCcw} loading={busy === `retry:${task.id}`} loadingText={i18nAttribute("排队中")} onClick={() => void mutate(task, 'retry')}><I18nText>重试</I18nText></Button> : null}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>

      <div className="mt-7 flex items-start gap-3 rounded-2xl border border-[#E3DED8] bg-[#FAF8F5] px-4 py-3 text-sm leading-6 text-[#706A63]">
        <Server size={17} className="mt-0.5 shrink-0" />
        <I18nText>发送任务由后台串行处理；服务在发送中断时会标记为“结果未知”，不会自动重复发送。</I18nText></div>
    </div>
  );
}
