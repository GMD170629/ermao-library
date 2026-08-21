'use client';

import { ArrowDown, ArrowUp, Bot, BookOpen, CheckCircle2, Database, ExternalLink, Headphones, Images, Save, Settings2, TestTube2, Trash2, X, type LucideIcon } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useToast } from '../../components/ui/feedback';
import { Select } from '../../components/ui/select';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type MediaKind = 'EBOOK' | 'COMIC' | 'AUDIOBOOK';

type ConfigField = {
  key: string;
  label: string;
  kind: string;
  required: boolean;
  secret: boolean;
  placeholder?: string | null;
  help?: string | null;
};

type MetadataProvider = {
  id: string;
  sourceId: string;
  name: string;
  version: string;
  description: string;
  mediaKinds: MediaKind[];
  configFields: ConfigField[];
  automaticRateLimit: { requests: number; periodSeconds: number } | null;
  config: Record<string, unknown>;
  configuredSecrets: Record<string, boolean>;
  lastTestAt: string | null;
  lastTestStatus: string | null;
  lastError: string | null;
};

type PipelineProvider = {
  providerId: string;
  name: string;
  description: string;
  enabled: boolean;
  position: number;
  lastTestStatus: string | null;
  lastError: string | null;
};

type ProviderPipeline = { mediaKind: MediaKind; providers: PipelineProvider[] };
type ProvidersResponse = {
  ok: boolean;
  data?: { providers?: MetadataProvider[]; pipelines?: ProviderPipeline[]; provider?: MetadataProvider; result?: { ok: boolean; message: string } };
  error?: { message: string };
};

const MEDIA_KIND_META: Record<MediaKind, { label: string; description: string; icon: LucideIcon }> = {
  EBOOK: { label: '电子书', description: 'EPUB、PDF 等文字读物的识别顺序', icon: BookOpen },
  COMIC: { label: '漫画', description: '漫画压缩包与条目的识别顺序', icon: Images },
  AUDIOBOOK: { label: '有声书', description: '音频资源、演播者与封面的识别顺序', icon: Headphones }
};

function mediaKindLabel(value: MediaKind) {
  return MEDIA_KIND_META[value]?.label ?? value;
}

function automaticRateLimitLabel(
  rateLimit: NonNullable<MetadataProvider['automaticRateLimit']>,
  translate: (message: string, values?: Record<string, string | number>) => string
) {
  if (rateLimit.periodSeconds === 1) {
    return translate('每秒最多 {value0} 次', { value0: rateLimit.requests });
  }
  return translate('每 {value0} 秒最多 {value1} 次', {
    value0: rateLimit.periodSeconds,
    value1: rateLimit.requests
  });
}

function ProviderIcon({ id, small = false }: { id: string; small?: boolean }) {
  const Icon = id === 'ai' ? Bot : Database;
  return <span className={`flex shrink-0 items-center justify-center rounded-2xl bg-[#FFF0EA] text-[#D94A2B] ${small ? 'h-9 w-9' : 'h-11 w-11'}`}><Icon size={small ? 17 : 20} /></span>;
}

function Toggle({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)} className={`relative h-7 w-12 rounded-full transition ${checked ? 'bg-[#FF5530]' : 'bg-[#D9D5CF]'} disabled:cursor-not-allowed disabled:opacity-50`}><span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow-sm transition ${checked ? 'left-6' : 'left-1'}`} /></button>;
}

export function MetadataProvidersPanel() {
  const { t: i18nAttribute } = useAttributeI18n();
  const toast = useToast();
  const [providers, setProviders] = useState<MetadataProvider[]>([]);
  const [pipelines, setPipelines] = useState<ProviderPipeline[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const editing = useMemo(() => providers.find((provider) => provider.id === editingId) ?? null, [editingId, providers]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/metadata/providers', { cache: 'no-store' });
      const payload = (await response.json()) as ProvidersResponse;
      if (!payload.ok || !payload.data) throw new Error(payload.error?.message ?? '读取数据源失败');
      setProviders(payload.data.providers ?? []);
      setPipelines(payload.data.pipelines ?? []);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取数据源失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!editingId) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function closeOnEscape(event: KeyboardEvent) { if (event.key === 'Escape') setEditingId(null); }
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [editingId]);

  function openEditor(provider: MetadataProvider) {
    setEditingId(provider.id);
    setDraft({ ...provider.config });
  }

  async function savePipeline(mediaKind: MediaKind, nextProviders: PipelineProvider[], message: string) {
    setBusy(`pipeline-${mediaKind}`);
    try {
      const response = await fetch(`/api/metadata/provider-pipelines/${mediaKind}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: nextProviders.map((item) => ({ providerId: item.providerId, enabled: item.enabled })) })
      });
      const payload = (await response.json()) as ProvidersResponse;
      if (!payload.ok || !payload.data?.pipelines) throw new Error(payload.error?.message ?? '保存识别顺序失败');
      setPipelines(payload.data.pipelines);
      if (payload.data.providers) setProviders(payload.data.providers);
      toast.success(message);
    } catch (reason) {
      toast.error('保存失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
    }
  }

  function changePipeline(mediaKind: MediaKind, transform: (items: PipelineProvider[]) => PipelineProvider[], message: string) {
    const current = pipelines.find((pipeline) => pipeline.mediaKind === mediaKind)?.providers ?? [];
    void savePipeline(mediaKind, transform(current), message);
  }

  function addProvider(mediaKind: MediaKind, providerId: string) {
    if (!providerId) return;
    const provider = providers.find((item) => item.id === providerId);
    if (!provider) return;
    changePipeline(mediaKind, (items) => [...items, {
      providerId: provider.id,
      name: provider.name,
      description: provider.description,
      enabled: false,
      position: (items.length + 1) * 100,
      lastTestStatus: provider.lastTestStatus,
      lastError: provider.lastError
    }], `${provider.name}已加入${mediaKindLabel(mediaKind)}识别`);
  }

  async function updateProvider(provider: MetadataProvider, body: Record<string, unknown>, successMessage?: string) {
    setBusy(provider.id);
    try {
      const response = await fetch(`/api/metadata/providers/${provider.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const payload = (await response.json()) as ProvidersResponse;
      if (!payload.ok || !payload.data?.provider) throw new Error(payload.error?.message ?? '更新数据源失败');
      setProviders((current) => current.map((item) => item.id === provider.id ? payload.data!.provider! : item));
      if (successMessage) toast.success(successMessage);
      return payload.data.provider;
    } catch (reason) {
      toast.error('更新失败', reason instanceof Error ? reason.message : '请检查数据源配置');
      return null;
    } finally {
      setBusy('');
    }
  }

  async function saveEditing() {
    if (!editing) return;
    const updated = await updateProvider(editing, { config: draft }, '数据源配置已保存');
    if (updated) setEditingId(null);
  }

  async function saveAndTestEditing() {
    if (!editing) return;
    const updated = await updateProvider(editing, { config: draft });
    if (updated) await testProvider(updated);
  }

  async function testProvider(provider: MetadataProvider) {
    setBusy(`test-${provider.id}`);
    try {
      const response = await fetch(`/api/metadata/providers/${provider.id}/test`, { method: 'POST' });
      const payload = (await response.json()) as ProvidersResponse;
      if (!payload.ok || !payload.data?.result) throw new Error(payload.error?.message ?? '连接测试失败');
      if (payload.data.provider) setProviders((current) => current.map((item) => item.id === provider.id ? payload.data!.provider! : item));
      if (payload.data.result.ok) toast.success(`${provider.name}连接正常`, payload.data.result.message);
      else toast.error(`${provider.name}连接失败`, payload.data.result.message);
    } catch (reason) {
      toast.error('连接测试失败', reason instanceof Error ? reason.message : '请检查网络和凭据');
    } finally {
      setBusy('');
    }
  }

  return (
    <div className="space-y-8">
      {error ? <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
      {loading ? <div className="shuku-loading-panel p-8 text-sm"><I18nText>正在读取数据源...</I18nText></div> : null}

      {!loading ? <section aria-labelledby="recognition-sources-title">
        <div className="mb-4">
          <h2 id="recognition-sources-title" className="text-xl font-semibold text-[#2C2926]"><I18nText>识别数据源</I18nText></h2>
          <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>为每类读物组合数据源。系统会按从上到下的顺序识别，只调用已启用的项目。</I18nText></p>
        </div>
        <div className="grid gap-4 xl:grid-cols-3">
          {(Object.keys(MEDIA_KIND_META) as MediaKind[]).map((mediaKind) => {
            const meta = MEDIA_KIND_META[mediaKind];
            const Icon = meta.icon;
            const items = pipelines.find((pipeline) => pipeline.mediaKind === mediaKind)?.providers ?? [];
            const available = providers.filter((provider) => provider.mediaKinds.includes(mediaKind) && !items.some((item) => item.providerId === provider.id));
            const isBusy = busy === `pipeline-${mediaKind}`;
            return <article key={mediaKind} className="overflow-visible rounded-[24px] border border-[#E2DDD7] bg-white shadow-sm shadow-stone-900/[0.03]">
              <header className="flex items-start justify-between gap-3 border-b border-[#EEEAE5] px-5 py-5">
                <div className="flex min-w-0 gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#FFF0EA] text-[#D94A2B]"><Icon size={20} /></span>
                  <div><h3 className="font-semibold text-[#2C2926]">{meta.label}</h3><p className="mt-1 text-xs leading-5 text-[#817A73]">{meta.description}</p></div>
                </div>
                <Badge tone="slate">{items.filter((item) => item.enabled).length}/{items.length} <I18nText>启用</I18nText></Badge>
              </header>
              <ol className="divide-y divide-[#EEEAE5] px-3" aria-label={i18nAttribute("{value0}数据源顺序", { value0: i18nAttribute(meta.label) })}>
                {items.map((item, index) => <li key={item.providerId} className="flex min-h-[74px] items-center gap-2 py-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#F5F1ED] text-[11px] tabular-nums text-[#7D766F]">{index + 1}</span>
                  <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-[#2C2926]">{item.name}</p><p className="mt-0.5 truncate text-xs text-[#918A83]">{item.enabled ? i18nAttribute("参与自动识别") : i18nAttribute("已停用")}</p></div>
                  <div className="flex items-center gap-0.5">
                    <button type="button" aria-label={i18nAttribute("上移{value0}", { value0: item.name })} disabled={isBusy || index === 0} onClick={() => changePipeline(mediaKind, (current) => { const next = [...current]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next; }, `${item.name}顺序已更新`)} className="flex h-8 w-8 items-center justify-center rounded-lg text-[#77716A] hover:bg-[#FFF0EA] hover:text-[#D94322] disabled:opacity-25"><ArrowUp size={15} /></button>
                    <button type="button" aria-label={i18nAttribute("下移{value0}", { value0: item.name })} disabled={isBusy || index === items.length - 1} onClick={() => changePipeline(mediaKind, (current) => { const next = [...current]; [next[index], next[index + 1]] = [next[index + 1], next[index]]; return next; }, `${item.name}顺序已更新`)} className="flex h-8 w-8 items-center justify-center rounded-lg text-[#77716A] hover:bg-[#FFF0EA] hover:text-[#D94322] disabled:opacity-25"><ArrowDown size={15} /></button>
                    <Toggle checked={item.enabled} disabled={isBusy} label={`${item.enabled ? '停用' : '启用'}${item.name}`} onChange={(enabled) => changePipeline(mediaKind, (current) => current.map((entry) => entry.providerId === item.providerId ? { ...entry, enabled } : entry), `${item.name}已${enabled ? '启用' : '停用'}`)} />
                    <button type="button" aria-label={i18nAttribute("从{value0}移除{value1}", { value0: i18nAttribute(meta.label), value1: item.name })} disabled={isBusy} onClick={() => changePipeline(mediaKind, (current) => current.filter((entry) => entry.providerId !== item.providerId), `${item.name}已移出${meta.label}识别`)} className="ml-1 flex h-8 w-8 items-center justify-center rounded-lg text-[#A39C95] hover:bg-red-50 hover:text-red-600 disabled:opacity-40"><Trash2 size={15} /></button>
                  </div>
                </li>)}
                {items.length === 0 ? <li className="py-7 text-center text-sm text-[#918A83]"><I18nText>尚未添加数据源</I18nText></li> : null}
              </ol>
              <div className="border-t border-[#EEEAE5] p-3">
                <Select value="" options={available.map((provider) => ({ value: provider.id, label: provider.name, translate: false }))} onChange={(value) => addProvider(mediaKind, value)} placeholder={available.length ? i18nAttribute("添加数据源") : i18nAttribute("没有更多可添加的数据源")} ariaLabel={i18nAttribute("为{value0}添加数据源", { value0: i18nAttribute(meta.label) })} disabled={isBusy || available.length === 0} className="w-full" triggerClassName="border-dashed" />
              </div>
            </article>;
          })}
        </div>
      </section> : null}

      {!loading ? <section aria-labelledby="provider-config-title" className="border-t border-[#E4DFD9] pt-7">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div><h2 id="provider-config-title" className="text-xl font-semibold text-[#2C2926]"><I18nText>数据源配置</I18nText></h2><p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>集中管理连接参数和凭据。启用与执行顺序在上方各读物区域中设置。</I18nText></p></div>
          <p className="text-xs text-[#918A83]"><I18nText>已发现 </I18nText>{providers.length} <I18nText>个数据源</I18nText></p>
        </div>
        <div className="overflow-hidden rounded-[24px] border border-[#E2DDD7] bg-white shadow-sm shadow-stone-900/[0.03]">
          <div className="hidden grid-cols-[minmax(240px,1.35fr)_minmax(180px,.8fr)_minmax(150px,.65fr)_180px] gap-4 border-b border-[#EEEAE5] bg-[#FAF8F6] px-5 py-3 text-xs font-medium text-[#77716A] md:grid"><span><I18nText>数据源</I18nText></span><span><I18nText>适用读物</I18nText></span><span><I18nText>连接状态</I18nText></span><span className="text-right"><I18nText>操作</I18nText></span></div>
          <div className="divide-y divide-[#EEEAE5]">
            {providers.map((provider) => <article key={provider.id} data-testid={`metadata-provider-${provider.id}`} className="grid gap-4 px-4 py-4 md:grid-cols-[minmax(240px,1.35fr)_minmax(180px,.8fr)_minmax(150px,.65fr)_180px] md:items-center md:px-5">
              <div className="flex min-w-0 items-center gap-3"><ProviderIcon id={provider.id} small /><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="truncate text-sm font-semibold text-[#2C2926]">{provider.name}</h3><Badge tone="slate">{provider.version}</Badge></div><p className="mt-0.5 truncate text-xs text-[#817A73]">{provider.description}</p></div></div>
              <div className="flex flex-wrap gap-1.5">{provider.mediaKinds.map((item) => <Badge key={item} tone="blue">{mediaKindLabel(item)}</Badge>)}</div>
              <div className="flex items-center gap-2 text-xs text-[#7C766F]">{provider.lastTestStatus === 'ok' ? <><CheckCircle2 size={15} className="text-emerald-600" /><I18nText>连接正常</I18nText></> : provider.lastTestStatus === 'failed' ? <><X size={15} className="text-red-500" /><span className="truncate">{provider.lastError || i18nAttribute("连接失败")}</span></> : <><I18nText>尚未测试</I18nText></>}</div>
              <div className="flex justify-end gap-2"><Button variant="ghost" icon={TestTube2} className="min-h-9 px-3 py-1.5 text-xs" loading={busy === `test-${provider.id}`} loadingText={i18nAttribute("测试中")} onClick={() => void testProvider(provider)}><I18nText>测试</I18nText></Button><Button variant="secondary" icon={Settings2} className="min-h-9 px-3 py-1.5 text-xs" onClick={() => openEditor(provider)}><I18nText>配置</I18nText></Button></div>
            </article>)}
          </div>
        </div>
      </section> : null}

      {editing ? <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#241F1C]/35 p-4 backdrop-blur-[2px] sm:p-6" role="dialog" aria-modal="true" aria-label={i18nAttribute("配置 {value0}", { value0: editing.name })} onMouseDown={(event) => { if (event.target === event.currentTarget) setEditingId(null); }}>
        <section className="max-h-[calc(100dvh-2rem)] w-full max-w-[640px] overflow-y-auto rounded-[26px] border border-[#E2DDD7] bg-[#FCFBF9] p-5 shadow-2xl shadow-stone-950/15 sm:max-h-[calc(100dvh-3rem)] sm:p-7">
          <div className="flex items-start justify-between gap-4 border-b border-[#E4DFD9] pb-5"><div className="flex gap-3"><ProviderIcon id={editing.id} /><div><h2 className="text-xl font-semibold text-[#292724]">{editing.name}</h2><p className="mt-1 text-sm text-[#77716A]"><I18nText>连接参数与访问凭据</I18nText></p></div></div><button type="button" aria-label={i18nAttribute("关闭数据源配置")} onClick={() => setEditingId(null)} className="flex h-10 w-10 items-center justify-center rounded-full border border-[#DED9D3] bg-white text-[#6D6760] hover:text-[#D94A2B]"><X size={18} /></button></div>
          <div className="mt-6 space-y-5">
            {editing.automaticRateLimit ? <label className="block text-sm font-medium text-[#5E5953]"><I18nText>自动识别限流</I18nText><input value={automaticRateLimitLabel(editing.automaticRateLimit, i18nAttribute)} type="text" readOnly aria-readonly="true" className="mt-2 h-11 w-full cursor-not-allowed rounded-xl border border-[#DCD7D1] bg-[#F3F0EC] px-4 text-sm text-[#6F6962] outline-none" /><span className="mt-1.5 block text-xs font-normal leading-5 text-[#88817A]"><I18nText>仅影响自动识别，手动识别不受限。</I18nText></span></label> : null}
            {editing.configFields.length === 0 ? <p className="rounded-2xl bg-[#F6F3EF] px-4 py-5 text-sm text-[#77716A]"><I18nText>此数据源无需额外配置。</I18nText></p> : null}
            {editing.configFields.map((field) => {
              const configured = field.secret && editing.configuredSecrets[field.key];
              return <label key={field.key} className="block text-sm font-medium text-[#5E5953]">{field.label}{field.required ? <span className="ml-1 text-[#E24C2C]">*</span> : null}<input value={String(draft[field.key] ?? '')} onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })} type={field.kind === 'password' ? 'password' : 'text'} autoComplete={field.secret ? 'new-password' : 'off'} placeholder={configured ? i18nAttribute("已配置，留空表示不修改") : field.placeholder ?? undefined} className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] bg-white px-4 text-sm text-[#2B2926] outline-none transition focus:border-[#EF8B73] focus:ring-4 focus:ring-[#FAD9D0]/70" />{field.help ? <span className="mt-1.5 block text-xs font-normal leading-5 text-[#88817A]">{field.help}</span> : null}</label>;
            })}
          </div>
          <div className="mt-8 flex flex-wrap justify-end gap-3 border-t border-[#E4DFD9] pt-5"><Button variant="secondary" icon={ExternalLink} loading={busy === editing.id || busy === `test-${editing.id}`} loadingText={i18nAttribute("测试中")} onClick={() => void saveAndTestEditing()}><I18nText>保存并测试</I18nText></Button><Button icon={Save} loading={busy === editing.id} loadingText={i18nAttribute("保存中")} onClick={() => void saveEditing()}><I18nText>保存配置</I18nText></Button></div>
        </section>
      </div> : null}
    </div>
  );
}
