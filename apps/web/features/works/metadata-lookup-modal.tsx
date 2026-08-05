'use client';

import { CheckCircle2, Search, Sparkles, X } from 'lucide-react';
import Image from 'next/image';
import { useEffect, useMemo, useState } from 'react';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { Select } from '../../components/ui/select';
import { withBasePath } from '../../lib/base-path';
import type { VolumeResource, WorkView } from '../../types/work';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { fetchAllMediaVersionVolumes } from './api/client';
import { completeMetadataApply } from './application/metadata-apply-completion';

type MetadataSource = string;
type MetadataField = 'coverUrl' | 'title' | 'author' | 'description' | 'tags' | 'seriesName' | 'publisher' | 'publishedAt' | 'language' | 'isbn';

type MetadataCandidate = {
  id: string;
  source: MetadataSource;
  title?: string | null;
  author?: string | null;
  description?: string | null;
  tags?: string[];
  seriesName?: string | null;
  volumeMetadata?: { publisher?: string | null; publishedAt?: string | null; language?: string | null; isbn?: string | null } | null;
  coverUrl?: string | null;
  confidence: number;
  raw: unknown;
};

type MetadataLookupModalProps = {
  book: WorkView;
  currentMediaVersionId?: string | null;
  open: boolean;
  onClose: () => void;
  onApplied: () => void | Promise<void>;
};

const fieldLabels: Record<MetadataField, string> = {
  coverUrl: '封面',
  title: '标题',
  author: '作者',
  description: '简介',
  tags: '标签',
  seriesName: '系列',
  publisher: '出版社',
  publishedAt: '出版时间',
  language: '语言',
  isbn: 'ISBN'
};

const fields: MetadataField[] = ['coverUrl', 'title', 'author', 'description', 'tags', 'seriesName', 'publisher', 'publishedAt', 'language', 'isbn'];
const volumeFields = new Set<MetadataField>(['publisher', 'publishedAt', 'language', 'isbn']);
const ALL_VOLUMES = '__all_volumes__';

function valueLabel(value: unknown) {
  if (Array.isArray(value)) return value.join(', ');
  if (value === null || value === undefined || value === '') return '未填写';
  return String(value);
}

function normalized(value: unknown) {
  return valueLabel(value).toLowerCase().replace(/[\s_\-.()[\]（）【】《》:：,，]+/g, '');
}

function candidateValue(candidate: MetadataCandidate | null, field: MetadataField) {
  if (!candidate) return null;
  if (field === 'publisher' || field === 'publishedAt' || field === 'language' || field === 'isbn') {
    return candidate.volumeMetadata?.[field] ?? null;
  }
  return candidate[field];
}

function bookValue(book: WorkView, field: MetadataField, targetVolume?: VolumeResource) {
  if (field === 'coverUrl') return book.coverStatus === 'READY' ? book.coverUrl : null;
  if (field === 'author') return book.author === '未知作者' ? null : book.author;
  if (field === 'description') return book.description || null;
  if (field === 'publisher' || field === 'publishedAt' || field === 'language' || field === 'isbn') return targetVolume?.[field] ?? null;
  if (field === 'tags') return book.tags;
  return field === 'title' || field === 'seriesName' ? book[field] : null;
}

function hasCandidateValue(value: unknown) {
  if (Array.isArray(value)) return value.length > 0;
  return value !== null && value !== undefined && value !== '';
}

function isCoverField(field: MetadataField) {
  return field === 'coverUrl';
}

function previewCoverUrl(value: string) {
  if (value.startsWith('/')) return withBasePath(value);
  return withBasePath(`/api/metadata/cover-proxy?url=${encodeURIComponent(value)}`);
}

function defaultFields(book: WorkView, candidate: MetadataCandidate | null, targetVolume?: VolumeResource) {
  if (!candidate) return [];
  return fields.filter((field) => {
    const next = candidateValue(candidate, field);
    if (!hasCandidateValue(next)) return false;
    if (isCoverField(field)) return book.coverStatus !== 'READY';
    return normalized(next) !== normalized(bookValue(book, field, targetVolume));
  });
}

function initialSource(book: WorkView): MetadataSource {
  return book.availableMediaKinds[0] === 'COMIC' ? 'bangumi' : 'douban';
}

type MetadataProviderOption = { id: string; name: string; enabled: boolean; mediaKinds: string[]; mode: string };
type MetadataProviderPipeline = { mediaKind: string; providers: Array<{ providerId: string; enabled: boolean }> };
type MetadataWritebackOperation = {
  id: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'COMPLETED_WITH_WARNINGS';
  totalTargets: number;
  completedTargets: number;
  warningTargets: number;
};

function selectedMediaKind(book: WorkView) {
  return book.availableMediaKinds[0] ?? 'EBOOK';
}

export function MetadataLookupModal({ book, currentMediaVersionId, open, onClose, onApplied }: MetadataLookupModalProps) {
  const { t: i18nAttribute, formatDate } = useAttributeI18n();
  const [source, setSource] = useState<MetadataSource>(() => initialSource(book));
  const [query, setQuery] = useState(book.title);
  const [candidates, setCandidates] = useState<MetadataCandidate[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [selectedFields, setSelectedFields] = useState<MetadataField[]>([]);
  const targetMediaVersion = useMemo(() => {
    const continuationVolume = book.mediaVersions
      .flatMap((mediaVersion) => mediaVersion.volumes)
      .find((volume) => volume.id === book.continueVolumeId);
    const fallbackMediaVersionId = continuationVolume?.mediaVersionId ?? book.mediaVersions[0]?.id;
    return book.mediaVersions.find((mediaVersion) => mediaVersion.id === (currentMediaVersionId ?? fallbackMediaVersionId)) ?? book.mediaVersions[0] ?? null;
  }, [book.continueVolumeId, book.mediaVersions, currentMediaVersionId]);
  const [targetVolumes, setTargetVolumes] = useState<VolumeResource[]>([]);
  const [volumeTarget, setVolumeTarget] = useState(ALL_VOLUMES);
  const selectedTargetVolume = volumeTarget === ALL_VOLUMES
    ? targetVolumes[0]
    : targetVolumes.find((volume) => volume.id === volumeTarget);
  const targetVolumeId = selectedTargetVolume?.id ?? null;
  const volumeTargetOptions = useMemo(() => [
    {
      value: ALL_VOLUMES,
      label: i18nAttribute('当前媒体版本的全部 {value0} 个卷册', { value0: targetMediaVersion?.volumeCount ?? targetVolumes.length }),
      translate: false
    },
    ...targetVolumes.map((volume) => ({ value: volume.id, label: volume.title, translate: false }))
  ], [i18nAttribute, targetMediaVersion?.volumeCount, targetVolumes]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [providers, setProviders] = useState<MetadataProviderOption[]>([]);
  const [enabledProviderIds, setEnabledProviderIds] = useState<string[]>([]);
  const [writeMetadataToFiles, setWriteMetadataToFiles] = useState(false);
  const [writebackOperation, setWritebackOperation] = useState<MetadataWritebackOperation | null>(null);

  const selected = useMemo(() => candidates.find((candidate) => candidate.id === selectedId) ?? candidates[0] ?? null, [candidates, selectedId]);
  const options = useMemo(() => providers.map((provider) => ({
    value: provider.id,
    label: provider.name,
    translate: false,
    disabled: !enabledProviderIds.includes(provider.id) || !provider.mediaKinds.includes(selectedMediaKind(book))
  })), [book, enabledProviderIds, providers]);
  const sourceReady = options.some((option) => option.value === source && !option.disabled);

  useEffect(() => {
    if (!open) return;
    const fallbackSource = initialSource(book);
    setSource(fallbackSource);
    setQuery(book.title);
    setCandidates([]);
    setSelectedId('');
    setSelectedFields([]);
    setMessage('');
    setError('');
    setWriteMetadataToFiles(false);
    setWritebackOperation(null);
    fetch('/api/organize/policy', { cache: 'no-store' })
      .then((response) => response.json() as Promise<{ ok: boolean; data?: { policy?: { writeMetadataToFiles?: boolean } } }>)
      .then((payload) => setWriteMetadataToFiles(Boolean(payload.ok && payload.data?.policy?.writeMetadataToFiles)))
      .catch(() => setWriteMetadataToFiles(false));
    fetch('/api/metadata/providers', { cache: 'no-store' })
      .then((response) => response.json() as Promise<{ ok: boolean; data?: { providers: MetadataProviderOption[]; pipelines?: MetadataProviderPipeline[] }; error?: { message: string } }>)
      .then((payload) => {
        if (!payload.ok) throw new Error(payload.error?.message ?? '读取元数据插件失败');
        const nextProviders = payload.data?.providers ?? [];
        const pipeline = (payload.data?.pipelines ?? []).find((item) => item.mediaKind === selectedMediaKind(book));
        const nextEnabledProviderIds = (pipeline?.providers ?? []).filter((item) => item.enabled).map((item) => item.providerId);
        setProviders(nextProviders);
        setEnabledProviderIds(nextEnabledProviderIds);
        const applicable = nextProviders.find((provider) => nextEnabledProviderIds.includes(provider.id) && provider.mediaKinds.includes(selectedMediaKind(book)));
        if (applicable) setSource(applicable.id);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : '读取元数据插件失败'));
  }, [book, open]);

  useEffect(() => {
    if (!open || !targetMediaVersion) return;
    const controller = new AbortController();
    setVolumeTarget(ALL_VOLUMES);
    setTargetVolumes(targetMediaVersion.volumes);
    void fetchAllMediaVersionVolumes(book.id, targetMediaVersion.id, controller.signal)
      .then(setTargetVolumes)
      .catch((reason) => {
        if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
          setError(i18nAttribute('无法读取当前媒体版本的卷册'));
        }
      });
    return () => controller.abort();
  }, [book.id, i18nAttribute, open, targetMediaVersion]);

  useEffect(() => {
    setSelectedFields(defaultFields(book, selected, targetVolumes[0]));
  }, [book, selected, targetVolumes]);

  useEffect(() => {
    if (!open || !writebackOperation || writebackOperation.status === 'COMPLETED' || writebackOperation.status === 'COMPLETED_WITH_WARNINGS') return;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const response = await fetch(`/api/metadata/writebacks/${encodeURIComponent(writebackOperation.id)}`, {
          cache: 'no-store',
          signal: controller.signal
        });
        const payload = (await response.json()) as { ok: boolean; data?: { operation?: MetadataWritebackOperation } };
        const operation = payload.ok ? payload.data?.operation : undefined;
        if (!operation) return;
        setWritebackOperation(operation);
        if (operation.status === 'COMPLETED') setMessage(i18nAttribute('元数据已保存，图书文件写回完成'));
        if (operation.status === 'COMPLETED_WITH_WARNINGS') setMessage(i18nAttribute('元数据已保存，{value0} 个文件写回失败', { value0: operation.warningTargets }));
      } catch (reason) {
        if (!(reason instanceof DOMException && reason.name === 'AbortError')) setError(i18nAttribute('无法读取文件写回进度'));
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [i18nAttribute, open, writebackOperation]);

  async function searchCandidates() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`/api/works/${book.id}/metadata/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, query })
      });
      const payload = (await response.json()) as { ok: boolean; data?: { candidates: MetadataCandidate[]; message?: string | null }; error?: { message: string } };
      if (!payload.ok) throw new Error(payload.error?.message ?? '元数据查询失败');
      const nextCandidates = payload.data?.candidates ?? [];
      setCandidates(nextCandidates);
      setSelectedId(nextCandidates[0]?.id ?? '');
      setMessage(nextCandidates.length ? `找到 ${nextCandidates.length} 条候选` : payload.data?.message ?? '没有找到候选');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '元数据查询失败');
    } finally {
      setBusy(false);
    }
  }

  async function applySelected() {
    if (!selected) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`/api/works/${book.id}/metadata/apply?applyToAllVolumes=${volumeTarget === ALL_VOLUMES ? 'true' : 'false'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source,
          candidate: selected,
          fields: selectedFields,
          volumeId: selectedFields.some((field) => volumeFields.has(field)) || writeMetadataToFiles ? targetVolumeId : null,
          writeMetadataToFiles
        })
      });
      const payload = (await response.json()) as { ok: boolean; data?: { metadataWriteback?: MetadataWritebackOperation | null }; error?: { message: string } };
      if (!payload.ok) throw new Error(payload.error?.message ?? '元数据应用失败');
      const operation = payload.data?.metadataWriteback ?? null;
      setWritebackOperation(operation);
      setMessage(operation ? i18nAttribute('已应用所选字段，正在后台写回图书文件') : i18nAttribute('已应用所选字段'));
      await completeMetadataApply({ close: onClose, refresh: onApplied });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '元数据应用失败');
    } finally {
      setBusy(false);
    }
  }

  function toggleField(field: MetadataField, checked: boolean) {
    setSelectedFields((current) => checked ? [...new Set([...current, field])] : current.filter((item) => item !== field));
  }

  function renderFieldValue(field: MetadataField, value: unknown, kind: 'current' | 'candidate') {
    if (!hasCandidateValue(value) && kind === 'candidate') return i18nAttribute('候选未提供该字段');
    if (field === 'publishedAt' && typeof value === 'string') {
      try {
        return formatDate(value, { dateStyle: 'medium' });
      } catch {
        return value;
      }
    }
    if (!isCoverField(field)) return valueLabel(value);
    if (typeof value !== 'string' || !value.trim()) return '未生成';
    return (
      <div className="flex items-center gap-3">
        <Image
          src={previewCoverUrl(value)}
          alt=""
          width={56}
          height={80}
          unoptimized
          className="h-20 w-14 rounded-lg border border-slate-200 object-cover"
        />
        <span className="text-xs text-slate-500">{kind === 'current' ? i18nAttribute("当前封面") : i18nAttribute("候选封面")}</span>
      </div>
    );
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[90] flex items-end justify-center bg-slate-950/40 p-0 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={i18nAttribute("元数据识别")}>
      <div className="flex max-h-[92dvh] w-full max-w-6xl flex-col overflow-hidden rounded-t-[28px] border border-slate-200 bg-white shadow-2xl shadow-slate-950/20 md:rounded-[28px]">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-950"><I18nText>元数据识别</I18nText></h2>
            <p className="mt-1 text-sm text-slate-500">{i18nAttribute('搜索候选，选择字段后应用到《{value0}》。', { value0: book.title })}</p>
          </div>
          <button type="button" onClick={onClose} className="flex h-10 w-10 items-center justify-center rounded-2xl text-slate-500 hover:bg-slate-100" aria-label={i18nAttribute("关闭")}>
            <X size={18} />
          </button>
        </div>

        <div className="grid gap-3 border-b border-slate-100 px-5 py-4 md:grid-cols-[180px_1fr_auto]">
          <Select value={source} options={options} onChange={setSource} ariaLabel={i18nAttribute("元数据来源")} className="w-full" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') void searchCandidates(); }}
            className="h-11 w-full rounded-2xl border border-slate-200 px-4 text-sm text-slate-900 outline-none focus:border-blue-300"
            placeholder={i18nAttribute("输入书名、系列名或关键词")}
          />
          <Button disabled={busy || !query.trim() || !sourceReady} icon={source === 'ai' ? Sparkles : Search} onClick={() => void searchCandidates()}>
            {source === 'ai' ? i18nAttribute("识别") : i18nAttribute("搜索")}
          </Button>
        </div>

        {(message || error) ? (
          <div className={cn('mx-5 mt-4 rounded-2xl px-4 py-3 text-sm', error ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700')}>
            {error || message}
          </div>
        ) : null}

        <div className="grid min-h-0 flex-1 gap-4 overflow-auto p-5 lg:grid-cols-[320px_1fr]">
          <div className="space-y-2">
            {candidates.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                onClick={() => setSelectedId(candidate.id)}
                className={cn('w-full rounded-2xl border p-3 text-left transition', selected?.id === candidate.id ? 'border-blue-200 bg-blue-50' : 'border-slate-200 hover:bg-slate-50')}
              >
                <div className="flex gap-3">
                  {candidate.coverUrl ? (
                    <Image
                      src={previewCoverUrl(candidate.coverUrl)}
                      alt=""
                      width={56}
                      height={80}
                      unoptimized
                      className="h-20 w-14 shrink-0 rounded-lg border border-slate-200 object-cover"
                    />
                  ) : null}
                  <div data-i18n-skip className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="line-clamp-2 font-medium text-slate-900">{candidate.title || i18nAttribute("未命名候选")}</div>
                      <Badge tone={candidate.confidence >= 0.8 ? 'green' : 'blue'}>{Math.round(candidate.confidence * 100)}%</Badge>
                    </div>
                    <div className="mt-1 line-clamp-1 text-xs text-slate-500">{candidate.author || candidate.seriesName || valueLabel(candidate.volumeMetadata?.isbn)}</div>
                    {candidate.description ? <div className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{candidate.description}</div> : null}
                  </div>
                </div>
              </button>
            ))}
            {candidates.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-200 p-6 text-sm text-slate-500"><I18nText>输入查询文本后开始搜索。</I18nText></div> : null}
          </div>

          <div className="min-w-0 rounded-2xl border border-slate-200">
            {selectedFields.some((field) => volumeFields.has(field)) || writeMetadataToFiles ? (
              <div className="border-b border-slate-100 bg-slate-50 px-3 py-3">
                <div className="mb-2 text-xs font-medium text-slate-500"><I18nText>卷册元数据应用范围</I18nText></div>
                <Select value={volumeTarget} options={volumeTargetOptions} onChange={setVolumeTarget} ariaLabel={i18nAttribute('卷册元数据应用范围')} className="w-full" />
              </div>
            ) : null}
            <div className="hidden grid-cols-[44px_90px_minmax(0,1fr)_minmax(0,1fr)] gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500 md:grid">
              <div />
              <div><I18nText>字段</I18nText></div>
              <div><I18nText>当前值</I18nText></div>
              <div><I18nText>候选值</I18nText></div>
            </div>
            <div className="divide-y divide-slate-100">
              {fields.map((field) => {
                const currentValue = bookValue(book, field, selectedTargetVolume);
                const nextValue = candidateValue(selected, field);
                const available = hasCandidateValue(nextValue);
                return (
                  <label key={field} title={!available ? i18nAttribute('候选未提供该字段') : undefined} className={cn('grid grid-cols-[28px_minmax(0,1fr)] gap-2 px-3 py-3 text-sm md:grid-cols-[44px_90px_minmax(0,1fr)_minmax(0,1fr)]', !available && 'text-slate-400')}>
                    <input
                      type="checkbox"
                      disabled={!available}
                      checked={selectedFields.includes(field)}
                      onChange={(event) => toggleField(field, event.target.checked)}
                      className="mt-1 h-4 w-4 accent-blue-600"
                    />
                    <div className="font-medium">{fieldLabels[field]}</div>
                    <div className="col-span-2 min-w-0 break-words pl-7 text-slate-500 md:col-auto md:pl-0">
                      <span className="mb-1 block text-xs text-slate-400 md:hidden"><I18nText>当前值</I18nText></span>
                      {renderFieldValue(field, currentValue, 'current')}
                    </div>
                    <div className="col-span-2 min-w-0 break-words pl-7 text-slate-900 md:col-auto md:pl-0">
                      <span className="mb-1 block text-xs text-slate-400 md:hidden"><I18nText>候选值</I18nText></span>
                      {renderFieldValue(field, nextValue, 'candidate')}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        </div>

        <div className="border-t border-slate-100 px-5 pt-4">
          <label className="flex items-start gap-3 rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
            <input type="checkbox" checked={writeMetadataToFiles} onChange={(event) => setWriteMetadataToFiles(event.target.checked)} className="mt-0.5 h-4 w-4 accent-blue-600" />
            <span><span className="block font-medium"><I18nText>同时覆盖图书文件元数据</I18nText></span><span className="mt-1 block text-xs text-slate-500"><I18nText>本次选择不会修改系统识别设置；文件将在后台安全写回。</I18nText></span></span>
          </label>
          {writebackOperation ? <div className="mt-2 text-xs text-slate-500"><I18nText>文件写回进度：</I18nText>{writebackOperation.completedTargets}/{writebackOperation.totalTargets}</div> : null}
        </div>
        <div className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose}><I18nText>取消</I18nText></Button>
          <Button disabled={busy || !selected || selectedFields.length === 0 || ((selectedFields.some((field) => volumeFields.has(field)) || writeMetadataToFiles) && !targetVolumeId)} icon={CheckCircle2} onClick={() => void applySelected()}><I18nText>应用所选字段</I18nText></Button>
        </div>
      </div>
    </div>
  );
}
