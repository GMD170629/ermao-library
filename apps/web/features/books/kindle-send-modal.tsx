'use client';

import { AlertTriangle, CheckCircle2, FileText, Mail, Send, Settings, X } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useToast } from '../../components/ui/feedback';
import type { BookView } from '../../types/book';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type KindleSettingsPayload = {
  ok: boolean;
  data?: {
    smtp: { configured: boolean; fromEmail: string };
    kindle: { email: string };
  };
  error?: { message: string };
};

type SendOption = {
  assetId: string;
  resourceId: string;
  resourceTitle: string;
  assetName: string;
  format: string;
  size: string;
};

function assetName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
}

function supported(path: string, format: string) {
  const suffix = path.toLowerCase().split('.').at(-1);
  return (format === 'EPUB' && suffix === 'epub') || (format === 'PDF' && suffix === 'pdf');
}

export function KindleSendModal({ book, open, preferredResourceId, onClose }: { book: BookView; open: boolean; preferredResourceId: string | null; onClose: () => void }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const toast = useToast();
  const options = useMemo<SendOption[]>(() => book.resources.flatMap((resource) => resource.assets
    .filter((asset) => supported(asset.path, resource.format))
    .map((asset) => ({
      assetId: asset.id,
      resourceId: resource.id,
      resourceTitle: resource.title,
      assetName: assetName(asset.path),
      format: resource.format,
      size: asset.size
    }))), [book.resources]);
  const defaultOption = options.find((option) => option.resourceId === preferredResourceId)
    ?? options[0];
  const [selectedAssetId, setSelectedAssetId] = useState(defaultOption?.assetId ?? '');
  const [recipient, setRecipient] = useState('');
  const [settingsReady, setSettingsReady] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsError, setSettingsError] = useState('');
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSelectedAssetId(defaultOption?.assetId ?? '');
    setSettingsLoading(true);
    setSettingsError('');
    fetch('/api/kindle-settings', { cache: 'no-store' })
      .then((response) => response.json())
      .then((payload: KindleSettingsPayload) => {
        if (!payload.ok || !payload.data) throw new Error(payload.error?.message ?? '读取邮件设置失败');
        const smtp = payload.data.smtp;
        setRecipient(payload.data.kindle.email);
        setSettingsReady(Boolean(smtp.configured && smtp.fromEmail && payload.data.kindle.email));
      })
      .catch((reason) => {
        setSettingsReady(false);
        setSettingsError(reason instanceof Error ? reason.message : '读取邮件设置失败');
      })
      .finally(() => setSettingsLoading(false));
  }, [defaultOption?.assetId, open]);

  if (!open) return null;

  async function enqueue() {
    if (!selectedAssetId) return;
    setSending(true);
    try {
      const response = await fetch('/api/kindle-send-tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bookId: book.id, assetId: selectedAssetId })
      });
      const payload = (await response.json()) as { ok: boolean; data?: { alreadyQueued: boolean }; error?: { message: string } };
      if (!payload.ok) throw new Error(payload.error?.message ?? '加入发送队列失败');
      toast.success(payload.data?.alreadyQueued ? '该文件已在发送队列中' : '已加入 Kindle 发送队列');
      onClose();
    } catch (reason) {
      toast.error('发送失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[95] flex items-end justify-center bg-stone-950/40 p-0 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={i18nAttribute("发送到 Kindle")}>
      <div className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-[28px] border border-stone-200 bg-white p-5 shadow-2xl md:rounded-[28px] md:p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#FFF0EA] text-[#DD4729]"><Send size={20} /></span>
            <div><h2 className="text-xl font-semibold text-stone-950"><I18nText>发送到 Kindle</I18nText></h2><p className="mt-1 text-sm leading-6 text-stone-600">{i18nAttribute('选择《{value0}》的一个 EPUB 或 PDF 文件加入后台队列。', { value0: book.title })}</p></div>
          </div>
          <button type="button" onClick={onClose} className="flex h-10 w-10 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100" aria-label={i18nAttribute("关闭")}><X size={18} /></button>
        </div>

        <div className="mt-5 rounded-2xl bg-[#F8F6F3] px-4 py-3 text-sm text-stone-600">
          <div className="flex items-center gap-2"><Mail size={16} className="text-stone-500" /><span className="font-medium text-stone-800"><I18nText>收件邮箱</I18nText></span><span className="min-w-0 break-all">{settingsLoading ? i18nAttribute("正在读取...") : recipient || i18nAttribute("尚未配置")}</span></div>
        </div>

        {!settingsLoading && !settingsReady ? (
          <div className="mt-4 flex flex-col gap-3 rounded-2xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800 sm:flex-row sm:items-center sm:justify-between">
            <span className="flex items-start gap-2"><AlertTriangle size={17} className="mt-0.5 shrink-0" />{settingsError || i18nAttribute("请先补全 SMTP 和 Kindle 邮箱设置。")}</span>
            <Link href="/settings/email?tab=kindle" className="inline-flex shrink-0 items-center gap-2 font-medium text-amber-900 hover:underline"><Settings size={15} /><I18nText>前往设置</I18nText></Link>
          </div>
        ) : null}

        <div className="mt-6">
          <h3 className="text-sm font-semibold text-stone-800"><I18nText>选择附件</I18nText></h3>
          <div className="mt-3 space-y-2">
            {options.map((option) => {
              const selected = selectedAssetId === option.assetId;
              return (
                <button key={option.assetId} type="button" onClick={() => setSelectedAssetId(option.assetId)} className={cn('flex w-full items-start gap-3 rounded-2xl border p-4 text-left transition', selected ? 'border-orange-200 bg-[#FFF5F1]' : 'border-stone-200 bg-white hover:border-stone-300 hover:bg-stone-50')}>
                  <span className={cn('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl', selected ? 'bg-[#ED4D2D] text-white' : 'bg-stone-100 text-stone-500')}>{selected ? <CheckCircle2 size={17} /> : <FileText size={17} />}</span>
                  <span className="min-w-0 flex-1"><span className="block font-medium text-stone-900">{option.resourceTitle}</span><span className="mt-1 block break-all text-xs leading-5 text-stone-500">{option.format} · {option.size} · {option.assetName}</span></span>
                </button>
              );
            })}
            {options.length === 0 ? <div className="rounded-2xl border border-dashed border-stone-300 px-5 py-8 text-center text-sm text-stone-500"><I18nText>这本图书没有可发送的 EPUB 或 PDF 文件。</I18nText></div> : null}
          </div>
        </div>

        <div className="mt-6 flex flex-col-reverse gap-3 border-t border-stone-100 pt-5 sm:flex-row sm:items-center sm:justify-between">
          <Link href="/settings/email?tab=queue" className="text-center text-sm font-medium text-[#D94322] hover:underline"><I18nText>查看发送队列</I18nText></Link>
          <div className="flex justify-end gap-3"><Button variant="secondary" onClick={onClose}><I18nText>取消</I18nText></Button><Button icon={Send} loading={sending} loadingText={i18nAttribute("加入中")} disabled={!settingsReady || !selectedAssetId} onClick={() => void enqueue()}><I18nText>加入发送队列</I18nText></Button></div>
        </div>
      </div>
    </div>
  );
}
