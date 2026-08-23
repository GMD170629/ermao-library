'use client';

import { CheckCircle2, Search, Sparkles, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { Select } from '../../components/ui/select';
import type { MediaKind, ReadableResourceView, BookView } from '../../types/book';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { completeMetadataApply } from './application/metadata-apply-completion';
import {
  fetchMetadataProviders,
  searchSourceNodeMetadata,
  updateResource,
  updateSourceNodeMetadata
} from './api/client';
import { mediaKindOfResource } from './book-detail';
import type { SourceNodeMetadataCandidate } from './model/book-contents';

type MetadataSource = string;
type MetadataField = 'title' | 'description';
type MetadataCandidate = SourceNodeMetadataCandidate;

type MetadataLookupModalProps = {
  book: BookView;
  currentResourceId?: string | null;
  fixedScope?: 'book' | 'resource' | null;
  open: boolean;
  onClose: () => void;
  onApplied: () => void | Promise<void>;
};

const fieldLabels: Record<MetadataField, string> = {
  title: '标题',
  description: '简介'
};

const fields: MetadataField[] = ['title', 'description'];

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
  return candidate[field];
}

function currentValueForField(book: BookView, field: MetadataField, targetResource?: ReadableResourceView) {
  if (field === 'title') return targetResource?.title ?? book.title;
  return targetResource?.description || book.description || null;
}

function hasCandidateValue(value: unknown) {
  if (Array.isArray(value)) return value.length > 0;
  return value !== null && value !== undefined && value !== '';
}

function defaultFields(book: BookView, candidate: MetadataCandidate | null, availableFields: MetadataField[], targetResource?: ReadableResourceView) {
  if (!candidate) return [];
  return availableFields.filter((field) => {
    const next = candidateValue(candidate, field);
    if (!hasCandidateValue(next)) return false;
    return normalized(next) !== normalized(currentValueForField(book, field, targetResource));
  });
}

function initialSource(resource: ReadableResourceView | undefined): MetadataSource {
  return resource && mediaKindOfResource(resource) === 'COMIC' ? 'bangumi' : 'douban';
}

type MetadataProviderOption = { id: string; name: string; enabled: boolean; mediaKinds: string[]; mode: string };
function selectedMediaKind(resource: ReadableResourceView | undefined): MediaKind {
  return resource ? mediaKindOfResource(resource) : 'EBOOK';
}

export function MetadataLookupModal({ book, currentResourceId, fixedScope = null, open, onClose, onApplied }: MetadataLookupModalProps) {
  const { t: i18nAttribute } = useAttributeI18n();
  const targetResource = useMemo(() => book.resources.find((resource) => resource.id === currentResourceId)
    ?? book.resources.find((resource) => resource.id === book.continueResourceId)
    ?? book.resources[0] ?? null, [book.continueResourceId, book.resources, currentResourceId]);
  const [source, setSource] = useState<MetadataSource>(() => initialSource(targetResource ?? undefined));
  const [query, setQuery] = useState(book.title);
  const [candidates, setCandidates] = useState<MetadataCandidate[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [selectedFields, setSelectedFields] = useState<MetadataField[]>([]);
  const selectedTargetResource = fixedScope === 'resource' ? targetResource : undefined;
  const kindResource = selectedTargetResource ?? targetResource;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [providers, setProviders] = useState<MetadataProviderOption[]>([]);
  const [enabledProviderIds, setEnabledProviderIds] = useState<string[]>([]);

  const selected = useMemo(() => candidates.find((candidate) => candidate.id === selectedId) ?? candidates[0] ?? null, [candidates, selectedId]);
  const options = useMemo(() => providers.map((provider) => ({
    value: provider.id,
    label: provider.name,
    translate: false,
    disabled: !enabledProviderIds.includes(provider.id) || !provider.mediaKinds.includes(selectedMediaKind(kindResource))
  })), [enabledProviderIds, kindResource, providers]);
  const sourceReady = options.some((option) => option.value === source && !option.disabled);

  useEffect(() => {
    if (!open) return;
    const fallbackSource = initialSource(kindResource);
    setSource(fallbackSource);
    setQuery(book.title);
    setCandidates([]);
    setSelectedId('');
    setSelectedFields([]);
    setMessage('');
    setError('');
    const controller = new AbortController();
    void fetchMetadataProviders(controller.signal)
      .then(({ providers: nextProviders, pipelines }) => {
        const mediaKind = selectedMediaKind(kindResource);
        const pipeline = pipelines.find((item) => item.mediaKind === mediaKind);
        const nextEnabledProviderIds = (pipeline?.providers ?? []).filter((item) => item.enabled).map((item) => item.providerId);
        setProviders(nextProviders);
        setEnabledProviderIds(nextEnabledProviderIds);
        const applicable = nextProviders.find((provider) => nextEnabledProviderIds.includes(provider.id) && provider.mediaKinds.includes(mediaKind));
        if (applicable) setSource(applicable.id);
      })
      .catch((reason) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取元数据插件失败'); });
    return () => controller.abort();
  }, [book, kindResource, open]);

  useEffect(() => {
    if (!open) return;
    setSelectedFields([]);
  }, [book.id, currentResourceId, fixedScope, open]);

  useEffect(() => {
    setSelectedFields(defaultFields(book, selected, fields, selectedTargetResource));
  }, [book, selected, selectedTargetResource]);

  async function searchCandidates() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const sourceNodeId = fixedScope === 'resource' ? targetResource?.sourceNodeId : book.sourceNodeId;
      if (!sourceNodeId) throw new Error('元数据目标缺少 sourceNodeId');
      const result = await searchSourceNodeMetadata(book.id, sourceNodeId, source, query.trim());
      const nextCandidates = result.candidates;
      setCandidates(nextCandidates);
      setSelectedId(nextCandidates[0]?.id ?? '');
      setMessage(nextCandidates.length ? `找到 ${nextCandidates.length} 条候选` : result.message ?? '没有找到候选');
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
      const title = selectedFields.includes('title') ? selected.title?.trim() : undefined;
      const description = selectedFields.includes('description') ? selected.description?.trim() || null : undefined;
      if (fixedScope === 'resource') {
        if (!targetResource) throw new Error('元数据目标资源不存在');
        await updateResource(book.id, targetResource.id, { ...(title ? { title } : {}), ...(description !== undefined ? { description } : {}) });
      } else {
        if (!book.sourceNodeId) throw new Error('元数据目标缺少 sourceNodeId');
        await updateSourceNodeMetadata(book.id, book.sourceNodeId, {
          title: title || book.title,
          description: description !== undefined ? description : book.description || null
        });
      }
      setMessage(i18nAttribute('已应用所选字段'));
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

  function renderFieldValue(value: unknown, kind: 'current' | 'candidate') {
    if (!hasCandidateValue(value) && kind === 'candidate') return i18nAttribute('候选未提供该字段');
    return valueLabel(value);
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
                  <div data-i18n-skip className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="line-clamp-2 font-medium text-slate-900">{candidate.title || i18nAttribute("未命名候选")}</div>
                      <Badge tone={candidate.confidence >= 0.8 ? 'green' : 'blue'}>{Math.round(candidate.confidence * 100)}%</Badge>
                    </div>
                    <div className="mt-1 line-clamp-1 text-xs text-slate-500">{candidate.source}</div>
                    {candidate.description ? <div className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{candidate.description}</div> : null}
                  </div>
                </div>
              </button>
            ))}
            {candidates.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-200 p-6 text-sm text-slate-500"><I18nText>输入查询文本后开始搜索。</I18nText></div> : null}
          </div>

          <div className="min-w-0 rounded-2xl border border-slate-200">
            <div className="hidden grid-cols-[44px_90px_minmax(0,1fr)_minmax(0,1fr)] gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500 md:grid">
              <div />
              <div><I18nText>字段</I18nText></div>
              <div><I18nText>当前值</I18nText></div>
              <div><I18nText>候选值</I18nText></div>
            </div>
            <div className="divide-y divide-slate-100">
              {fields.map((field) => {
                const currentValue = currentValueForField(book, field, selectedTargetResource);
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
                      {renderFieldValue(currentValue, 'current')}
                    </div>
                    <div className="col-span-2 min-w-0 break-words pl-7 text-slate-900 md:col-auto md:pl-0">
                      <span className="mb-1 block text-xs text-slate-400 md:hidden"><I18nText>候选值</I18nText></span>
                      {renderFieldValue(nextValue, 'candidate')}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose}><I18nText>取消</I18nText></Button>
          <Button disabled={busy || !selected || selectedFields.length === 0 || (fixedScope === 'resource' && !targetResource)} icon={CheckCircle2} onClick={() => void applySelected()}><I18nText>应用所选字段</I18nText></Button>
        </div>
      </div>
    </div>
  );
}
