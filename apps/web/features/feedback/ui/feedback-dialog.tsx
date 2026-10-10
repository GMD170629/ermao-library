'use client';

import { sha256 } from '@noble/hashes/sha2.js';
import { Bold, CheckCircle2, ChevronRight, FileImage, ImagePlus, List, Paperclip, Send, X } from 'lucide-react';
import Image from 'next/image';
import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button } from '../../../components/ui/button';
import { Select } from '../../../components/ui/select';
import { useI18n } from '../../../i18n/provider';
import {
  FeedbackApiError, fetchFeedbackEnvironment, previewFeedback, submitFeedback,
  type FeedbackClientEnvironment, type FeedbackContact, type FeedbackDraft,
  type FeedbackEnvironment, type FeedbackKind, type FeedbackPreview, type InstallationMethod
} from '../api';

const TEMPLATES: Record<FeedbackKind, string> = {
  suggestion: '### 我希望增加或改善\n\n\n### 使用场景\n\n\n### 期望效果\n\n',
  issue: '### 遇到的现象\n\n\n### 我做了什么\n\n\n### 期望结果\n\n'
};
const ACCEPT = '.png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.log,.zip';
const ALLOWED = /\.(png|jpe?g|webp|gif|pdf|txt|log|zip)$/i;
type SelectedFile = { id: string; file: File; url: string; image: boolean };
type Step = 'form' | 'review' | 'sending' | 'success' | 'failure';

function newUuid(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function clientEnvironment(locale: 'zh-CN' | 'en-US'): FeedbackClientEnvironment {
  return {
    client: window.matchMedia('(display-mode: standalone)').matches ? 'pwa' : 'web',
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    languages: [...navigator.languages],
    locale,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown',
    viewport: `${window.innerWidth} × ${window.innerHeight}`,
    screen: `${window.screen.width} × ${window.screen.height}`,
    devicePixelRatio: window.devicePixelRatio,
    colorDepth: window.screen.colorDepth,
    page: window.location.pathname
  };
}

function hasDescription(markdown: string) {
  return Boolean(markdown.replace(/^#{1,6}\s+.*$/gm, '').replace(/!\[[^\]]*\]\(upload:[^)]+\)/g, '').replace(/[\s*`#>-]/g, '').trim());
}

function MarkdownContent({ markdown, files }: { markdown: string; files: SelectedFile[] }) {
  return <div data-i18n-skip className="prose prose-sm max-w-none break-words text-[#3B3631] [&_h3]:mt-4 [&_h3]:font-semibold [&_p]:my-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
    <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={(url) => url.startsWith('upload:') ? url : ''} components={{
      img: ({ src, alt }) => {
        const selected = files.find((item) => item.image && src === `upload:${item.id}`);
        return selected ? <Image unoptimized src={selected.url} width={600} height={240} alt={alt ?? ''} className="my-2 max-h-60 max-w-full rounded-xl border border-[#DEDAD4] object-contain" /> : <span>{alt}</span>;
      },
      a: ({ children }) => <span>{children}</span>
    }}>{markdown}</ReactMarkdown>
  </div>;
}

function Diagnostics({ diagnostics }: { diagnostics: Record<string, unknown> }) {
  return <pre data-i18n-skip className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-[#E5D7D1] bg-white p-3 text-xs leading-5 text-[#514A44]">{JSON.stringify(diagnostics, null, 2)}</pre>;
}

export function FeedbackDialog({ initialKind, eventId, onClose }: { initialKind: FeedbackKind; eventId?: string; onClose: () => void }) {
  const { t, locale } = useI18n();
  const errorText = useCallback((reason: unknown, fallback: string): string => {
    if (!(reason instanceof FeedbackApiError)) return t(fallback);
    const message = {
      FEEDBACK_LOG_FORBIDDEN: '需要系统管理权限',
      FEEDBACK_LOG_NOT_FOUND: '日志已不可用',
      FEEDBACK_ENVIRONMENT_INVALID: '系统环境信息不完整',
      FEEDBACK_INVALID: '反馈内容无效',
      FEEDBACK_FILES_TOO_LARGE: '附件大小超限',
      FEEDBACK_FILE_INVALID: '不支持的附件格式',
      FEEDBACK_DELIVERY_FAILED: '反馈暂时无法发送，请稍后重试'
    }[reason.code];
    return t(message ?? fallback);
  }, [t]);
  const [step, setStep] = useState<Step>('form');
  const [kind, setKind] = useState<FeedbackKind>(initialKind);
  const [markdown, setMarkdown] = useState(() => t(TEMPLATES[initialKind]));
  const [contact, setContact] = useState<FeedbackContact>({ qq: '', groupName: '', email: '' });
  const [includeLog, setIncludeLog] = useState(Boolean(eventId));
  const [includeEnvironment, setIncludeEnvironment] = useState(false);
  const [installationMethod, setInstallationMethod] = useState<InstallationMethod | ''>('');
  const [environment, setEnvironment] = useState<FeedbackEnvironment | null>(null);
  const [environmentOpen, setEnvironmentOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [logPreview, setLogPreview] = useState<FeedbackPreview | null>(null);
  const [files, setFiles] = useState<SelectedFile[]>([]);
  const [editorMode, setEditorMode] = useState<'write' | 'preview'>('write');
  const [showEmail, setShowEmail] = useState(false);
  const [preview, setPreview] = useState<FeedbackPreview | null>(null);
  const [reviewDraft, setReviewDraft] = useState<FeedbackDraft | null>(null);
  const [receiptId, setReceiptId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submissionKey = useRef('');
  const textRef = useRef<HTMLTextAreaElement>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const filesRef = useRef<SelectedFile[]>([]);

  useEffect(() => { filesRef.current = files; }, [files]);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButton.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      for (const item of filesRef.current) URL.revokeObjectURL(item.url);
      previous?.focus();
    };
  }, []);
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && step !== 'sending') {
        if (document.querySelector('[role="listbox"]')) return;
        event.preventDefault(); onClose(); return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]):not([tabindex="-1"]), select:not([disabled]), textarea:not([disabled]), a[href]'));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!dialogRef.current.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose, step]);
  useEffect(() => {
    if (!includeEnvironment || environment) return;
    const controller = new AbortController();
    void fetchFeedbackEnvironment(controller.signal).then(setEnvironment).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(errorText(reason, '读取系统环境失败'));
    });
    return () => controller.abort();
  }, [environment, includeEnvironment, errorText]);

  const buildDraft = useCallback(async (): Promise<FeedbackDraft> => ({
    kind, markdown, contact, includeEnvironment,
    installationMethod: includeEnvironment && installationMethod ? installationMethod : null,
    clientEnvironment: includeEnvironment ? clientEnvironment(locale) : null,
    eventId: kind === 'issue' && includeLog ? eventId ?? null : null,
    files: await Promise.all(files.map(async (item) => ({
      name: item.file.name, size: item.file.size,
      sha256: Array.from(sha256(new Uint8Array(await item.file.arrayBuffer())))
        .map((value) => value.toString(16).padStart(2, '0')).join('')
    })))
  }), [contact, eventId, files, includeEnvironment, includeLog, installationMethod, kind, locale, markdown]);

  function addFiles(incoming: FileList | File[]) {
    if (busy) return;
    const selected = Array.from(incoming);
    let total = files.reduce((sum, item) => sum + item.file.size, 0);
    const accepted: SelectedFile[] = [];
    let fileError = '';
    for (const file of selected) {
      if (files.length + accepted.length >= 5) { fileError = t('最多添加 5 个文件'); break; }
      if (!ALLOWED.test(file.name)) { fileError = t('不支持的附件格式'); continue; }
      if (file.size > 10 * 1024 * 1024 || total + file.size > 15 * 1024 * 1024) { fileError = t('附件大小超限'); continue; }
      total += file.size;
      accepted.push({ id: newUuid(), file, url: URL.createObjectURL(file), image: /\.(png|jpe?g|webp|gif)$/i.test(file.name) });
    }
    if (accepted.length) {
      setFiles((current) => [...current, ...accepted]);
      setMarkdown((current) => current + accepted.filter((item) => item.image).map((item) => `\n![${item.file.name.replace(/[\[\]()]/g, '')}](upload:${item.id})\n`).join(''));
    }
    setError(fileError);
  }

  function removeFile(id: string) {
    const item = files.find((candidate) => candidate.id === id);
    if (!item) return;
    URL.revokeObjectURL(item.url);
    setFiles((current) => current.filter((candidate) => candidate.id !== id));
    setMarkdown((current) => current.replace(new RegExp(`!\\[[^\\]]*\\]\\(upload:${id}\\)`, 'g'), ''));
  }

  function insertMarkdown(before: string, after: string, fallback: string) {
    const input = textRef.current;
    if (!input) return;
    const start = input.selectionStart;
    const end = input.selectionEnd;
    const content = input.value.slice(start, end) || fallback;
    setMarkdown(input.value.slice(0, start) + before + content + after + input.value.slice(end));
    requestAnimationFrame(() => { input.focus(); input.setSelectionRange(start + before.length, start + before.length + content.length); });
  }

  async function showLog() {
    if (!eventId) return;
    if (logOpen) { setLogOpen(false); return; }
    setBusy(true);
    try {
      const result = await previewFeedback(await buildDraft());
      setLogPreview(result);
      setLogOpen(true);
      setError('');
    } catch (reason) { setError(errorText(reason, '读取日志预览失败')); }
    finally { setBusy(false); }
  }

  async function review() {
    if (!hasDescription(markdown)) { setError(t('请在提纲中填写具体内容')); return; }
    if (includeEnvironment && !installationMethod) { setError(t('请选择安装方式')); return; }
    if (contact.qq && !/^\d{1,20}$/.test(contact.qq)) { setError(t('QQ 号请填写数字')); return; }
    if (contact.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact.email)) { setError(t('请填写有效邮箱地址')); return; }
    setBusy(true);
    try {
      const draft = await buildDraft();
      const result = await previewFeedback(draft);
      setPreview(result);
      setReviewDraft(draft);
      submissionKey.current = newUuid();
      setStep('review');
      setError('');
    } catch (reason) { setError(errorText(reason, '无法核对反馈')); }
    finally { setBusy(false); }
  }

  async function submit() {
    if (!preview || !reviewDraft || !submissionKey.current) return;
    setStep('sending');
    try {
      const receipt = await submitFeedback(reviewDraft, preview.previewHash, submissionKey.current, files.map((item) => item.file));
      setReceiptId(receipt.id);
      for (const item of files) URL.revokeObjectURL(item.url);
      setFiles([]);
      setStep('success');
    } catch (reason) {
      if (reason instanceof FeedbackApiError && reason.code === 'FEEDBACK_PREVIEW_CHANGED') {
        setError(t('内容已变化，请重新核对'));
        setStep('form');
      } else {
        setError(errorText(reason, '提交暂时失败'));
        setStep('failure');
      }
    }
  }

  function changeKind(next: FeedbackKind) {
    if (next === kind) return;
    if (markdown.trim() === t(TEMPLATES[kind]).trim()) setMarkdown(t(TEMPLATES[next]));
    setKind(next);
    if (next === 'suggestion') setIncludeLog(false);
    setError('');
  }

  const descriptor = kind === 'issue' ? t('问题描述') : t('详细说明');
  return <div className="fixed inset-0 z-[130] flex items-end justify-center bg-[#1C1815A8] backdrop-blur-[3px] sm:items-center sm:p-5" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && step !== 'sending') onClose(); }}>
    <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="feedback-title" className="flex max-h-[94vh] w-full max-w-[740px] flex-col overflow-hidden rounded-t-[26px] border border-[#E6DED7] bg-white shadow-2xl sm:max-h-[92vh] sm:rounded-[26px]">
      <header className="flex items-start justify-between gap-3 border-b border-[#EEE9E4] px-5 py-5 sm:px-6">
        <h2 id="feedback-title" className="text-xl font-semibold text-[#20201F]">{t(step === 'review' ? '核对反馈内容' : '反馈与报错')}</h2>
        <button ref={closeButton} type="button" disabled={step === 'sending'} onClick={onClose} aria-label={t('关闭弹窗')} className="rounded-lg p-2 text-[#77716A] hover:bg-[#F7F5F2] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#ED4D2D]"><X size={18} /></button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
        {step === 'form' ? <fieldset disabled={busy} className="m-0 min-w-0 border-0 p-0">
          <div role="tablist" aria-label={t('反馈类型')} className="mb-5 grid grid-cols-2 rounded-xl bg-[#F7F5F2] p-1">
            {(['suggestion', 'issue'] as const).map((item) => <button key={item} type="button" role="tab" aria-selected={kind === item} onClick={() => changeKind(item)} className={`min-h-10 rounded-lg text-sm font-semibold ${kind === item ? 'bg-white text-[#ED4D2D] shadow-sm' : 'text-[#6C665F]'}`}>{t(item === 'suggestion' ? '功能建议' : '遇到问题')}</button>)}
          </div>
          {eventId && kind === 'issue' ? <section className="mb-5 rounded-2xl border border-[#F0D9D0] bg-[#FFF8F5] p-4 text-sm"><strong>{t('所选日志')} {eventId}</strong><label className="mt-3 flex gap-2"><input type="checkbox" checked={includeLog} onChange={(event) => { setIncludeLog(event.target.checked); setLogOpen(false); }} />{t('提交时附上这条完整日志')}</label><button type="button" disabled={!includeLog || busy} onClick={() => void showLog()} className="mt-2 text-sm font-medium text-[#D94322]">{t(logOpen ? '收起将发送的日志' : '查看将发送的日志')}</button>{logOpen && logPreview ? <Diagnostics diagnostics={logPreview.diagnostics} /> : null}</section> : null}
          <label htmlFor="feedback-markdown" className="mb-2 block text-sm font-semibold">{descriptor} <span className="text-[#ED4D2D]">*</span></label>
          <div className="overflow-hidden rounded-2xl border border-[#DEDAD4] focus-within:border-[#F0A28F] focus-within:ring-2 focus-within:ring-[#FAD9D0]" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); addFiles(event.dataTransfer.files); }}>
            <div className="flex items-center justify-between gap-2 border-b border-[#E9E2DC] bg-[#FBFAF8] p-2">
              <div className="flex items-center gap-1"><button type="button" onClick={() => insertMarkdown('**', '**', t('重点内容'))} aria-label={t('加粗')} className="rounded-lg p-2 hover:bg-[#F0E9E4]"><Bold size={17} /></button><button type="button" onClick={() => insertMarkdown('- ', '', t('列表项'))} aria-label={t('插入列表')} className="rounded-lg p-2 hover:bg-[#F0E9E4]"><List size={17} /></button><span className="mx-1 h-5 w-px bg-[#DDD5CE]" /><button type="button" onClick={() => imageInput.current?.click()} aria-label={t('上传图片')} className="rounded-lg p-2 hover:bg-[#F0E9E4]"><ImagePlus size={17} /></button><button type="button" onClick={() => fileInput.current?.click()} aria-label={t('上传附件')} className="rounded-lg p-2 hover:bg-[#F0E9E4]"><Paperclip size={17} /></button></div>
              <div className="flex rounded-lg bg-[#F1EDE9] p-0.5 text-xs"><button type="button" onClick={() => setEditorMode('write')} className={`rounded-md px-2 py-1 ${editorMode === 'write' ? 'bg-white text-[#D94322]' : ''}`}>{t('编辑')}</button><button type="button" onClick={() => setEditorMode('preview')} className={`rounded-md px-2 py-1 ${editorMode === 'preview' ? 'bg-white text-[#D94322]' : ''}`}>{t('预览')}</button></div>
            </div>
            {editorMode === 'write' ? <textarea ref={textRef} id="feedback-markdown" value={markdown} maxLength={20000} onChange={(event) => setMarkdown(event.target.value)} className="block min-h-60 w-full resize-y p-4 font-mono text-[13px] leading-6 outline-none" /> : <div className="min-h-60 p-4"><MarkdownContent markdown={markdown} files={files} /></div>}
            <p className="border-t border-[#EEE9E4] px-3 py-2 text-[11px] text-[#918A83]">{t('支持 Markdown · 可拖入图片或文件 · 最多 5 个、单个不超过 10 MB、合计不超过 15 MB')}</p>
          </div>
          <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple className="sr-only" tabIndex={-1} onChange={(event) => { if (event.target.files) addFiles(event.target.files); event.target.value = ''; }} />
          <input ref={fileInput} type="file" accept={ACCEPT} multiple className="sr-only" tabIndex={-1} onChange={(event) => { if (event.target.files) addFiles(event.target.files); event.target.value = ''; }} />
          {files.length ? <div className="mt-3 space-y-2">{files.map((item) => <div key={item.id} className="flex items-center gap-2 rounded-xl border border-[#E9E2DC] bg-[#FCFBF9] p-2">{item.image ? <Image unoptimized src={item.url} width={40} height={40} alt="" className="h-10 w-10 rounded-lg object-cover" /> : <Paperclip size={18} className="mx-3 text-[#D94322]" />}<span data-i18n-skip className="min-w-0 flex-1 truncate text-xs">{item.file.name} · {(item.file.size / 1024).toFixed(0)} KB</span><button type="button" onClick={() => removeFile(item.id)} aria-label={t('移除附件')} className="rounded-lg p-1.5 hover:bg-[#F7F5F2]"><X size={16} /></button></div>)}</div> : null}
          <section className="mt-6 border-t border-[#EEE9E4] pt-4"><h3 className="text-sm font-semibold">{t('系统环境（选填）')}</h3><label className="mt-3 flex gap-2 text-sm"><input type="checkbox" checked={includeEnvironment} onChange={(event) => { setIncludeEnvironment(event.target.checked); if (!event.target.checked) setEnvironmentOpen(false); }} />{t('同步系统环境信息')}</label>{includeEnvironment ? <div className="mt-3 text-xs font-semibold"><span>{t('安装方式')}</span><Select<InstallationMethod | ''> value={installationMethod} onChange={setInstallationMethod} options={[{ value: 'app-store', label: '应用商店安装' }, { value: 'manual', label: '手动安装' }, { value: 'docker', label: 'Docker 安装' }]} placeholder="请选择安装方式" ariaLabel="安装方式" className="mt-1 w-full" triggerClassName="!border-[#DEDAD4] !text-[#34312E]" menuClassName="!z-[140]" /></div> : null}<button type="button" disabled={!includeEnvironment} onClick={() => setEnvironmentOpen(!environmentOpen)} className="mt-3 text-sm font-medium text-[#D94322] disabled:text-[#918A83]">{t(environmentOpen ? '收起环境信息' : '查看会收集哪些信息')}</button>{environmentOpen && includeEnvironment ? <Diagnostics diagnostics={{ environment: { appVersion: environment?.appVersion ?? t('读取中…'), installationMethod: installationMethod ? t({ 'app-store': '应用商店安装', manual: '手动安装', docker: 'Docker 安装' }[installationMethod]) : t('请选择安装方式'), ...clientEnvironment(locale) } }} /> : null}<p className="mt-2 text-xs text-[#918A83]">{t('不包含账号、令牌、IP 地址、书库路径或图书列表。')}</p></section>
          <section className="mt-6 border-t border-[#EEE9E4] pt-4"><h3 className="text-sm font-semibold">{t('联系方式（选填）')}</h3><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-xs font-semibold">{t('QQ 号')}<input value={contact.qq} maxLength={20} onChange={(event) => setContact({ ...contact, qq: event.target.value })} placeholder={t('方便联系你的 QQ 号')} className="mt-1 block h-11 w-full rounded-xl border border-[#DEDAD4] px-3 text-sm outline-none focus:border-[#F0A28F]" /></label><label className="text-xs font-semibold">{t('官方交流群昵称')}<input value={contact.groupName} maxLength={100} onChange={(event) => setContact({ ...contact, groupName: event.target.value })} placeholder={t('仅群成员填写')} className="mt-1 block h-11 w-full rounded-xl border border-[#DEDAD4] px-3 text-sm outline-none focus:border-[#F0A28F]" /></label></div><button type="button" onClick={() => setShowEmail(!showEmail)} className="mt-3 text-sm font-medium text-[#D94322]">{t(showEmail ? '收起邮箱联系方式' : '使用邮箱联系')}</button>{showEmail ? <label className="mt-2 block text-xs font-semibold">{t('邮箱')}<input type="email" value={contact.email} maxLength={254} onChange={(event) => setContact({ ...contact, email: event.target.value })} placeholder="name@example.com" className="mt-1 block h-11 w-full rounded-xl border border-[#DEDAD4] px-3 text-sm outline-none focus:border-[#F0A28F]" /></label> : null}</section>
        </fieldset> : null}
        {step === 'review' && preview ? <><p className="rounded-xl border border-[#F2D7C7] bg-[#FFF8F2] p-3 text-sm text-[#7A5B45]">{t('请核对以下将发送的内容。')}</p><section className="mt-4 rounded-2xl border border-[#E8E1DA] p-4"><h3 className="mb-2 text-sm font-semibold">{descriptor}</h3><MarkdownContent markdown={markdown} files={files} /><p data-i18n-skip className="mt-3 text-xs">{contact.qq ? `QQ: ${contact.qq}  ` : ''}{contact.groupName ? `${t('官方交流群昵称')}: ${contact.groupName}  ` : ''}{contact.email ? `${t('邮箱')}: ${contact.email}` : ''}</p></section><section className="mt-3 rounded-2xl border border-[#E8E1DA] p-4"><h3 className="text-sm font-semibold">{t('图片与附件')} · {files.length}</h3>{files.map((item) => <p key={item.id} data-i18n-skip className="mt-2 flex items-center gap-2 text-xs">{item.image ? <FileImage size={15} /> : <Paperclip size={15} />}{item.file.name}</p>)}</section><section className="mt-3 rounded-2xl border border-[#E8E1DA] p-4"><h3 className="text-sm font-semibold">{t('诊断信息')}</h3>{Object.keys(preview.diagnostics).length ? <Diagnostics diagnostics={preview.diagnostics} /> : <p className="mt-2 text-xs text-[#918A83]">{t('未附带诊断信息。')}</p>}</section></> : null}
        {step === 'sending' ? <div className="py-14 text-center"><h3 className="text-xl font-semibold">{t('正在提交')}</h3><p className="mt-2 text-sm text-[#77716A]">{t('正在将反馈送往官网，请稍候。')}</p></div> : null}
        {step === 'success' ? <div className="py-12 text-center"><CheckCircle2 size={48} className="mx-auto text-green-600" /><h3 className="mt-4 text-xl font-semibold">{t('反馈已收到')}</h3><p data-i18n-skip className="mt-3 rounded-xl bg-[#F7F5F2] px-4 py-2 font-mono text-sm">{receiptId}</p><p className="mt-3 text-sm text-[#77716A]">{t('临时文件已清除。请保存反馈编号，方便在交流群中沟通。')}</p></div> : null}
        {step === 'failure' ? <div className="py-12 text-center"><h3 className="text-xl font-semibold">{t('提交暂时失败')}</h3><p className="mt-2 text-sm text-[#77716A]">{t('官网临时文件已清除；当前浏览器仍保留正文和附件。可重试或返回修改。')}</p></div> : null}
        {error ? <p role="alert" className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
      </div>
      <footer className="flex items-center justify-end gap-2 border-t border-[#EEE9E4] px-5 py-4 sm:px-6"><span className="mr-auto hidden text-xs text-[#918A83] sm:block">{t('反馈与报错')}</span>{step === 'form' ? <><Button variant="secondary" onClick={onClose}>{t('取消')}</Button><Button disabled={busy} onClick={() => void review()}>{t('核对内容')}<ChevronRight size={16} /></Button></> : null}{step === 'review' ? <><Button variant="secondary" onClick={() => { setStep('form'); setError(''); }}>{t('返回修改')}</Button><Button onClick={() => void submit()}><Send size={16} />{t('确认提交')}</Button></> : null}{step === 'failure' ? <><Button variant="secondary" onClick={() => { setStep('form'); setError(''); }}>{t('返回修改')}</Button><Button onClick={() => void submit()}>{t('重试提交')}</Button></> : null}{step === 'success' ? <Button onClick={onClose}>{t('完成')}</Button> : null}</footer>
    </section>
  </div>;
}
