'use client';

import { ArrowDown, ArrowUp, Clock3, Save, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Button } from '../../components/ui/button';
import { useToast } from '../../components/ui/feedback';
import { Select } from '../../components/ui/select';
import { useI18n } from '../../i18n/provider';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

export type OrganizePolicy = {
  id: string;
  enabled: boolean;
  scheduleMode: 'MANUAL' | 'INTERVAL';
  intervalMinutes: number;
  autoRunOnNew: boolean;
  autoRunOnNewSince: string | null;
  rules: { unrecognized: boolean; missingMetadata: boolean };
  writeMetadataToFiles: boolean;
  preferLocalMetadata: boolean;
  localMetadataPriority: LocalMetadataSource[];
  lastScheduledAt: string | null;
  nextRunAt: string | null;
  updatedAt: string | null;
};

type LocalMetadataSource = 'SIDECAR_OPF' | 'EMBEDDED' | 'PATH';

type PolicyResponse = { ok: boolean; data?: { policy: OrganizePolicy }; error?: { message: string } };
type CandidateResponse = { ok: boolean; data?: { candidates: { total: number } }; error?: { message: string } };
type OpfQueueResponse = { ok: boolean; data?: { queue: { pendingTargets: number; capacity: number; utilization: number } } };

const defaultPolicy: OrganizePolicy = {
  id: 'default',
  enabled: false,
  scheduleMode: 'MANUAL',
  intervalMinutes: 60,
  autoRunOnNew: false,
  autoRunOnNewSince: null,
  rules: { unrecognized: true, missingMetadata: true },
  writeMetadataToFiles: false,
  preferLocalMetadata: true,
  localMetadataPriority: ['SIDECAR_OPF', 'EMBEDDED', 'PATH'],
  lastScheduledAt: null,
  nextRunAt: null,
  updatedAt: null
};

function Toggle({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${checked ? 'bg-[#FF5530]' : 'bg-[#D9D5CF]'} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow-sm transition ${checked ? 'left-6' : 'left-1'}`} />
    </button>
  );
}

function settingRow(title: string, description: string, control: React.ReactNode) {
  return (
    <div className="flex items-start justify-between gap-5 border-b border-[#EEEAE5] py-5 last:border-b-0">
      <div className="min-w-0"><div className="text-sm font-semibold text-[#302D29]">{title}</div><p className="mt-1 text-sm leading-6 text-[#7B756E]">{description}</p></div>
      {control}
    </div>
  );
}

export function RecognitionSettingsPanel({ compact = false, onSaved }: { compact?: boolean; onSaved?: (policy: OrganizePolicy) => void }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const toast = useToast();
  const { locale } = useI18n();
  const [policy, setPolicy] = useState<OrganizePolicy>(defaultPolicy);
  const [candidateCount, setCandidateCount] = useState(0);
  const [opfQueue, setOpfQueue] = useState({ pendingTargets: 0, capacity: 50000, utilization: 0 });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [policyResponse, candidateResponse, queueResponse] = await Promise.all([
        fetch('/api/organize/policy', { cache: 'no-store' }),
        fetch('/api/organize/candidates', { cache: 'no-store' }),
        fetch('/api/metadata/opf-sync/status', { cache: 'no-store' })
      ]);
      const policyPayload = (await policyResponse.json()) as PolicyResponse;
      const candidatePayload = (await candidateResponse.json()) as CandidateResponse;
      const queuePayload = (await queueResponse.json()) as OpfQueueResponse;
      if (!policyPayload.ok || !policyPayload.data?.policy) throw new Error(policyPayload.error?.message ?? '读取识别设置失败');
      setPolicy(policyPayload.data.policy);
      if (candidatePayload.ok) setCandidateCount(candidatePayload.data?.candidates.total ?? 0);
      if (queuePayload.ok && queuePayload.data?.queue) setOpfQueue(queuePayload.data.queue);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取识别设置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function save() {
    setBusy('save');
    try {
      const response = await fetch('/api/organize/policy', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(policy)
      });
      const payload = (await response.json()) as PolicyResponse;
      if (!payload.ok || !payload.data?.policy) throw new Error(payload.error?.message ?? '保存识别设置失败');
      setPolicy(payload.data.policy);
      onSaved?.(payload.data.policy);
      toast.success('识别设置已保存');
      await load();
    } catch (reason) {
      toast.error('操作失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setBusy('');
    }
  }

  const cardClass = compact ? '' : 'max-w-4xl rounded-[26px] border border-[#E2DDD7] bg-white p-5 shadow-sm shadow-stone-900/[0.03] sm:p-6';
  const intervalOptions = [15, 30, 60, 180, 360, 720, 1440].map((value) => ({
    value: String(value),
    label: value < 60
      ? i18nAttribute('{value0} 分钟', { value0: value })
      : value === 60
        ? i18nAttribute('每小时')
        : value === 1440
          ? i18nAttribute('每天')
          : i18nAttribute('每 {value0} 小时', { value0: value / 60 }),
    translate: false
  }));
  const sourceLabels: Record<LocalMetadataSource, string> = {
    SIDECAR_OPF: i18nAttribute('OPF 文件'),
    EMBEDDED: i18nAttribute('文件内部元数据'),
    PATH: i18nAttribute('文件路径')
  };
  function moveSource(index: number, offset: -1 | 1) {
    const target = index + offset;
    if (target < 0 || target >= policy.localMetadataPriority.length) return;
    const next = [...policy.localMetadataPriority];
    [next[index], next[target]] = [next[target], next[index]];
    setPolicy({ ...policy, localMetadataPriority: next });
  }
  return (
    <div className={cardClass}>
      {!compact ? (
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FFF0EA] text-[#DD4729]"><Sparkles size={19} /></span>
          <div><h3 className="text-lg font-semibold text-[#292724]"><I18nText>元数据识别策略</I18nText></h3><p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>控制哪些读物进入整理队列，以及识别任务何时执行。</I18nText></p></div>
        </div>
      ) : null}
      {error ? <div className="mt-4 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
      <div className={compact ? '' : 'mt-5'}>
        {settingRow('定时执行识别', '开启后按固定间隔扫描书库；导入流程本身不会直接创建整理任务。', <Toggle checked={policy.enabled && policy.scheduleMode === 'INTERVAL'} disabled={loading} label={i18nAttribute("定时执行识别")} onChange={(checked) => setPolicy({ ...policy, enabled: checked, scheduleMode: checked ? 'INTERVAL' : 'MANUAL' })} />)}
        {policy.enabled && policy.scheduleMode === 'INTERVAL' ? settingRow('执行间隔', '建议至少 30 分钟，避免对外部数据源产生过密请求。', <Select value={String(policy.intervalMinutes)} options={intervalOptions} ariaLabel="识别任务执行间隔" onChange={(value) => setPolicy({ ...policy, intervalMinutes: Number(value) })} className="min-w-36" triggerClassName="!border-[#DCD7D1] !text-[#393632]" />) : null}
        {settingRow('新增后自动执行', '仅处理开启此设置之后新增的读物，历史书库不会被一次性加入。', <Toggle checked={policy.autoRunOnNew} disabled={loading} label={i18nAttribute("新增后自动执行")} onChange={(autoRunOnNew) => setPolicy({ ...policy, autoRunOnNew })} />)}
        {settingRow(i18nAttribute('元数据变化自动保存到旁车 OPF'), i18nAttribute('开启后，仅观察之后发生的图书、资源和有声书元数据变化；异步生成 OPF 和独立封面，源图书资产始终保持不变。关闭后不再新增任务，已排队任务会继续完成。'), <Toggle checked={policy.writeMetadataToFiles} disabled={loading} label={i18nAttribute('元数据变化自动保存到旁车 OPF')} onChange={(writeMetadataToFiles) => setPolicy({ ...policy, writeMetadataToFiles })} />)}
        {policy.writeMetadataToFiles ? settingRow(i18nAttribute('OPF 保存队列'), i18nAttribute('当前待处理 {value0} / {value1} 个目标；达到容量时，新变更仍会保存到书库，但该批 OPF 任务会被丢弃并记录系统警告。', { value0: opfQueue.pendingTargets, value1: opfQueue.capacity }), <span className="shrink-0 text-sm font-semibold text-[#625D57]">{Math.round(opfQueue.utilization * 100)}%</span>) : null}
        {settingRow(i18nAttribute('本地元数据优先'), i18nAttribute('开启后远程数据仅作为补充'), <Toggle checked={policy.preferLocalMetadata} disabled={loading} label={i18nAttribute('本地元数据优先')} onChange={(preferLocalMetadata) => setPolicy({ ...policy, preferLocalMetadata })} />)}
      </div>

      <div className="mt-5 rounded-2xl border border-[#E8E3DD] p-4">
        <div className="text-sm font-semibold text-[#3B3834]"><I18nText>本地元数据识别顺序</I18nText></div>
        <p className="mt-1 text-sm leading-6 text-[#7B756E]"><I18nText>按字段从上到下选择；高优先级来源缺少字段时，才由下一来源补充。</I18nText></p>
        <ol className="mt-3 space-y-2">
          {policy.localMetadataPriority.map((source, index) => (
            <li key={source} className="flex items-center gap-3 rounded-xl bg-[#F8F6F3] px-3 py-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white text-xs font-semibold text-[#7B756E]">{index + 1}</span>
              <span className="min-w-0 flex-1 text-sm font-medium text-[#3B3834]">{sourceLabels[source]}</span>
              <Button variant="ghost" className="!min-h-9 !px-2" icon={ArrowUp} disabled={loading || index === 0} aria-label={i18nAttribute('上移{value0}', { value0: sourceLabels[source] })} onClick={() => moveSource(index, -1)} />
              <Button variant="ghost" className="!min-h-9 !px-2" icon={ArrowDown} disabled={loading || index === policy.localMetadataPriority.length - 1} aria-label={i18nAttribute('下移{value0}', { value0: sourceLabels[source] })} onClick={() => moveSource(index, 1)} />
            </li>
          ))}
        </ol>
      </div>

      <div className="mt-5 rounded-2xl bg-[#F8F6F3] p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-[#3B3834]"><Clock3 size={16} className="text-[#DB4D2D]" /><I18nText>识别范围</I18nText></div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="flex items-center gap-3 text-sm text-[#625D57]"><input type="checkbox" checked={policy.rules.unrecognized} onChange={(event) => setPolicy({ ...policy, rules: { ...policy.rules, unrecognized: event.target.checked } })} className="h-4 w-4 accent-[#FF5530]" /><I18nText>尚未识别的读物</I18nText></label>
          <label className="flex items-center gap-3 text-sm text-[#625D57]"><input type="checkbox" checked={policy.rules.missingMetadata} onChange={(event) => setPolicy({ ...policy, rules: { ...policy.rules, missingMetadata: event.target.checked } })} className="h-4 w-4 accent-[#FF5530]" /><I18nText>缺少作者或封面</I18nText></label>
        </div>
      </div>

      <div className="mt-5 flex flex-col gap-3 rounded-2xl border border-[#F1D8CF] bg-[#FFF8F5] px-4 py-3 text-sm text-[#8A4C3C] sm:flex-row sm:items-center sm:justify-between">
        <span><I18nText>按当前规则，书库中有 </I18nText><strong>{candidateCount}</strong> <I18nText>本读物可加入整理队列。</I18nText></span>
        {policy.nextRunAt ? <span className="text-xs"><I18nText>下次执行：</I18nText>{new Date(policy.nextRunAt).toLocaleString(locale)}</span> : null}
      </div>
      <div className="mt-6 flex flex-wrap justify-end gap-3">
        <Button icon={Save} loading={busy === 'save'} loadingText={i18nAttribute("保存中")} onClick={() => void save()}><I18nText>保存设置</I18nText></Button>
      </div>
    </div>
  );
}
