'use client';

import { AlertTriangle, Ban, BookOpen, Clock3, Mail, RefreshCw, RotateCcw, Send, Server, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, type BadgeTone } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useConfirm, useToast } from '../../components/ui/feedback';
import { useI18n } from '../../i18n/provider';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

export type KindleSendTask = {
  id: string;
  bookId: string | null;
  resourceId: string;
  assetId: string | null;
  bookTitle: string;
  resourceTitle: string | null;
  assetName: string;
  resourceFormat: string;
  mimeType: string;
  sizeBytes: number;
  senderEmail: string | null;
  recipientEmail: string;
  subject: string;
  smtpHost: string | null;
  smtpPort: number | null;
  smtpSecurity: string | null;
  smtpUsername: string | null;
  messageId: string | null;
  status: 'queued' | 'sending' | 'sent' | 'failed' | 'cancelled' | 'unknown';
  attemptCount: number;
  nextAttemptAt: string | null;
  errorMessage: string | null;
  startedAt: string | null;
  sentAt: string | null;
  createdAt: string;
  updatedAt: string;
  canCancel: boolean;
  canRetry: boolean;
  canDelete: boolean;
};

type TasksPayload = {
  ok: boolean;
  data?: { tasks: KindleSendTask[]; total: number };
  error?: { message: string };
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

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${index === 0 ? Math.round(size) : size.toFixed(1)} ${units[index]}`;
}

function dateLabel(value: string | null, locale: string) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale);
}

function securityLabel(value: string | null) {
  return { starttls: 'STARTTLS', ssl: 'SSL/TLS', none: '无加密' }[value ?? ''] ?? value ?? '未记录';
}

export function KindleSendQueuePage({ embedded = false }: { embedded?: boolean }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const { locale } = useI18n();
  const toast = useToast();
  const confirm = useConfirm();
  const [tasks, setTasks] = useState<KindleSendTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const loadTasks = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const response = await fetch('/api/kindle-send-tasks?pageSize=200', { cache: 'no-store' });
      const payload = (await response.json()) as TasksPayload;
      if (!payload.ok) throw new Error(payload.error?.message ?? '读取发送队列失败');
      setTasks(payload.data?.tasks ?? []);
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

  async function mutate(task: KindleSendTask, action: 'cancel' | 'retry' | 'delete') {
    if (action === 'delete' && !await confirm({ title: '删除发送记录', description: `删除《${task.bookTitle}》的发送记录？`, confirmLabel: '删除', tone: 'danger' })) return;
    setBusy(`${action}:${task.id}`);
    try {
      const response = await fetch(
        action === 'delete' ? `/api/kindle-send-tasks/${task.id}` : `/api/kindle-send-tasks/${task.id}/${action}`,
        { method: action === 'delete' ? 'DELETE' : 'POST' }
      );
      const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
      if (!payload.ok) throw new Error(payload.error?.message ?? '操作失败');
      toast.success(action === 'cancel' ? '已取消发送' : action === 'retry' ? '已重新排队' : '发送记录已删除');
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
                        <h5 className="break-words font-semibold text-[#242220]">{task.bookTitle}</h5>
                        <Badge tone={statusTone(task.status)}>{statusLabels[task.status]}</Badge>
                        <Badge>{task.resourceFormat}</Badge>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-[#6F6962]">
                        <span className="rounded-full bg-[#F3F0EC] px-2.5 py-1">{task.resourceTitle ?? task.assetName}</span>
                        <span className="rounded-full bg-[#F3F0EC] px-2.5 py-1">{task.assetName}</span>
                        <span className="rounded-full bg-[#F3F0EC] px-2.5 py-1">{formatBytes(task.sizeBytes)}</span>
                        <span className="rounded-full bg-[#F3F0EC] px-2.5 py-1"><I18nText>尝试 </I18nText>{task.attemptCount} <I18nText>次</I18nText></span>
                      </div>
                      <dl className="mt-4 grid gap-3 rounded-2xl bg-[#F8F6F3] p-4 text-xs text-[#655F58] sm:grid-cols-2 xl:grid-cols-3">
                        <div><dt className="text-[#9A938B]"><I18nText>收件邮箱</I18nText></dt><dd className="mt-1 break-all font-medium text-[#433F3B]">{task.recipientEmail}</dd></div>
                        <div><dt className="text-[#9A938B]"><I18nText>发件邮箱</I18nText></dt><dd className="mt-1 break-all font-medium text-[#433F3B]">{task.senderEmail ?? i18nAttribute("等待发送时确定")}</dd></div>
                        <div><dt className="text-[#9A938B]">SMTP</dt><dd className="mt-1 font-medium text-[#433F3B]">{task.smtpHost ? `${task.smtpHost}:${task.smtpPort ?? ''} · ${securityLabel(task.smtpSecurity)}` : i18nAttribute("等待发送时确定")}</dd></div>
                        <div><dt className="text-[#9A938B]"><I18nText>创建时间</I18nText></dt><dd className="mt-1 font-medium text-[#433F3B]">{dateLabel(task.createdAt, locale)}</dd></div>
                        <div><dt className="text-[#9A938B]"><I18nText>提交时间</I18nText></dt><dd className="mt-1 font-medium text-[#433F3B]">{dateLabel(task.sentAt, locale)}</dd></div>
                        <div><dt className="text-[#9A938B]">Message-ID</dt><dd className="mt-1 truncate font-medium text-[#433F3B]" title={task.messageId ?? ''}>{task.messageId ?? '—'}</dd></div>
                      </dl>
                      {task.nextAttemptAt ? <div className="mt-3 flex items-center gap-2 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-700"><Clock3 size={16} /><I18nText>下次尝试：</I18nText>{dateLabel(task.nextAttemptAt, locale)}</div> : null}
                      {task.errorMessage ? <div className="mt-3 flex gap-2 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><span className="break-words">{task.errorMessage}</span></div> : null}
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      {task.bookId ? <Link href={`/books/${task.bookId}`} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#DED8D1] bg-white px-4 py-2.5 text-sm font-medium text-[#4F4B47] transition hover:border-[#F2B7A6] hover:bg-[#FFF5F1] hover:text-[#D94322]"><BookOpen size={16} /><I18nText>查看图书</I18nText></Link> : null}
                      {task.canCancel ? <Button variant="secondary" icon={Ban} loading={busy === `cancel:${task.id}`} loadingText={i18nAttribute("取消中")} onClick={() => void mutate(task, 'cancel')}><I18nText>取消</I18nText></Button> : null}
                      {task.canRetry ? <Button variant="secondary" icon={RotateCcw} loading={busy === `retry:${task.id}`} loadingText={i18nAttribute("排队中")} onClick={() => void mutate(task, 'retry')}><I18nText>重试</I18nText></Button> : null}
                      {task.canDelete ? <Button variant="danger" icon={Trash2} loading={busy === `delete:${task.id}`} loadingText={i18nAttribute("删除中")} onClick={() => void mutate(task, 'delete')}><I18nText>删除</I18nText></Button> : null}
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
