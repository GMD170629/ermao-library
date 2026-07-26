'use client';

import type {
  Page_ProviderResponse_,
  ProviderResponse
} from '@/generated/api-v2';
import { I18nText, useI18n as useAttributeI18n } from '@/i18n/provider';
import { apiV2Request } from '@/lib/api-v2';
import { Database, Save, Settings2, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useToast } from '../../components/ui/feedback';

type WorkType = 'ebook' | 'comic' | 'audiobook';

const WORK_TYPES: Array<{ value: WorkType; label: string }> = [
  { value: 'ebook', label: '电子书' },
  { value: 'comic', label: '漫画' },
  { value: 'audiobook', label: '有声书' }
];

function configuredWorkTypes(provider: ProviderResponse): WorkType[] {
  const value = provider.config.workTypes;
  if (!Array.isArray(value)) return WORK_TYPES.map((item) => item.value);
  return value.filter(
    (item): item is WorkType => item === 'ebook' || item === 'comic' || item === 'audiobook'
  );
}

export function MetadataProvidersPanel() {
  const { t: i18nAttribute } = useAttributeI18n();
  const toast = useToast();
  const [providers, setProviders] = useState<ProviderResponse[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState('');
  const [draftPriority, setDraftPriority] = useState(100);
  const [draftEnabled, setDraftEnabled] = useState(false);
  const [draftWorkTypes, setDraftWorkTypes] = useState<WorkType[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const editing = useMemo(
    () => providers.find((provider) => provider.id === editingId) ?? null,
    [editingId, providers]
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await apiV2Request<Page_ProviderResponse_>(
        '/api/v2/metadata/providers',
        { cache: 'no-store' }
      );
      setProviders(page.items);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取数据源失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!editingId) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setEditingId(null);
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [editingId]);

  function openEditor(provider: ProviderResponse) {
    setEditingId(provider.id);
    setDraftName(provider.name);
    setDraftPriority(provider.priority);
    setDraftEnabled(provider.enabled);
    setDraftWorkTypes(configuredWorkTypes(provider));
  }

  function toggleWorkType(workType: WorkType) {
    setDraftWorkTypes((current) => current.includes(workType)
      ? current.filter((item) => item !== workType)
      : [...current, workType]);
  }

  async function save() {
    if (!editing) return;
    setBusy(true);
    try {
      const updated = await apiV2Request<ProviderResponse>(
        `/api/v2/metadata/providers/${encodeURIComponent(editing.id)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: draftName.trim(),
            enabled: draftEnabled,
            priority: draftPriority,
            config: {
              ...editing.config,
              workTypes: draftWorkTypes
            }
          })
        }
      );
      setProviders((current) => current.map((provider) => (
        provider.id === updated.id ? updated : provider
      )));
      setEditingId(null);
      toast.success('数据源配置已保存');
    } catch (reason) {
      toast.error('保存失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-[#2C2926]"><I18nText>识别数据源</I18nText></h2>
        <p className="mt-1 text-sm leading-6 text-[#77716A]">
          <I18nText>配置已注册的数据源、适用读物与执行优先级。</I18nText>
        </p>
      </div>

      {error ? (
        <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {loading ? (
        <div className="shuku-loading-panel p-8 text-sm"><I18nText>正在读取数据源...</I18nText></div>
      ) : null}

      {!loading && providers.length === 0 ? (
        <div className="rounded-[24px] border border-dashed border-[#DCD7D1] bg-white p-8 text-center text-sm text-[#77716A]">
          <I18nText>尚未注册元数据数据源。</I18nText>
        </div>
      ) : null}

      {!loading && providers.length > 0 ? (
        <div className="overflow-hidden rounded-[24px] border border-[#E2DDD7] bg-white shadow-sm">
          <div className="divide-y divide-[#EEEAE5]">
            {providers.map((provider) => (
              <article
                key={provider.id}
                data-testid={`metadata-provider-${provider.id}`}
                className="grid gap-4 px-5 py-5 md:grid-cols-[minmax(220px,1fr)_minmax(180px,.8fr)_120px_110px] md:items-center"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#FFF0EA] text-[#D94A2B]">
                    <Database size={18} />
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-[#2C2926]">{provider.name}</div>
                    <div className="mt-0.5 truncate text-xs text-[#817A73]">{provider.slug}</div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {configuredWorkTypes(provider).map((workType) => (
                    <Badge key={workType} tone="blue">
                      {WORK_TYPES.find((item) => item.value === workType)?.label ?? workType}
                    </Badge>
                  ))}
                </div>
                <div className="text-sm text-[#716B64]">
                  <I18nText>优先级 </I18nText>{provider.priority}
                </div>
                <div className="flex items-center justify-end gap-2">
                  <Badge tone={provider.enabled ? 'green' : 'slate'}>
                    {provider.enabled ? i18nAttribute('已启用') : i18nAttribute('已停用')}
                  </Badge>
                  <Button
                    variant="ghost"
                    icon={Settings2}
                    className="min-h-9 px-3 py-1.5 text-xs"
                    onClick={() => openEditor(provider)}
                  >
                    <I18nText>配置</I18nText>
                  </Button>
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {editing ? (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-[#241F1C]/35 p-4 backdrop-blur-[2px]"
          role="dialog"
          aria-modal="true"
          aria-label={i18nAttribute('配置 {value0}', { value0: editing.name })}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setEditingId(null);
          }}
        >
          <section className="w-full max-w-xl rounded-[26px] border border-[#E2DDD7] bg-[#FCFBF9] p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-[#E4DFD9] pb-5">
              <div>
                <h2 className="text-xl font-semibold text-[#292724]">{editing.name}</h2>
                <p className="mt-1 text-sm text-[#77716A]">{editing.slug}</p>
              </div>
              <button
                type="button"
                aria-label={i18nAttribute('关闭数据源配置')}
                onClick={() => setEditingId(null)}
                className="flex h-10 w-10 items-center justify-center rounded-full border border-[#DED9D3] bg-white text-[#6D6760]"
              >
                <X size={18} />
              </button>
            </div>

            <div className="mt-6 space-y-5">
              <label className="block text-sm font-medium text-[#5E5953]">
                <I18nText>显示名称</I18nText>
                <input
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] bg-white px-4 text-sm outline-none focus:border-[#EF8B73]"
                />
              </label>
              <label className="block text-sm font-medium text-[#5E5953]">
                <I18nText>执行优先级</I18nText>
                <input
                  type="number"
                  min={0}
                  max={10000}
                  value={draftPriority}
                  onChange={(event) => setDraftPriority(Number(event.target.value))}
                  className="mt-2 h-11 w-full rounded-xl border border-[#DCD7D1] bg-white px-4 text-sm outline-none focus:border-[#EF8B73]"
                />
              </label>
              <fieldset>
                <legend className="text-sm font-medium text-[#5E5953]"><I18nText>适用读物</I18nText></legend>
                <div className="mt-2 flex flex-wrap gap-3">
                  {WORK_TYPES.map((workType) => (
                    <label key={workType.value} className="flex items-center gap-2 text-sm text-[#625D57]">
                      <input
                        type="checkbox"
                        checked={draftWorkTypes.includes(workType.value)}
                        onChange={() => toggleWorkType(workType.value)}
                        className="h-4 w-4 accent-[#FF5530]"
                      />
                      {workType.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="flex items-center justify-between gap-4 rounded-2xl bg-[#F6F3EF] px-4 py-3 text-sm font-medium text-[#5E5953]">
                <I18nText>启用此数据源</I18nText>
                <input
                  type="checkbox"
                  checked={draftEnabled}
                  onChange={(event) => setDraftEnabled(event.target.checked)}
                  className="h-5 w-5 accent-[#FF5530]"
                />
              </label>
            </div>

            <div className="mt-8 flex justify-end gap-3 border-t border-[#E4DFD9] pt-5">
              <Button variant="secondary" onClick={() => setEditingId(null)}><I18nText>取消</I18nText></Button>
              <Button
                icon={Save}
                loading={busy}
                loadingText={i18nAttribute('保存中')}
                disabled={!draftName.trim() || draftWorkTypes.length === 0}
                onClick={() => void save()}
              >
                <I18nText>保存配置</I18nText>
              </Button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
