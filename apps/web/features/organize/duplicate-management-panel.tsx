'use client';

import type {
  DuplicateGroupResponse,
  DuplicateWorkResponse,
  LibraryOperationResponse,
  Page_DuplicateGroupResponse_
} from '@/generated/api-v2';
import { apiV2Request } from '@/lib/api-v2';

import { CheckCircle2, GitMerge, Loader2, RotateCcw, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useToast } from '../../components/ui/feedback';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

function workTags(work: DuplicateWorkResponse) {
  const tags = work.metadata.tags;
  return Array.isArray(tags)
    ? tags.filter((value): value is string => typeof value === 'string')
    : [];
}

export function DuplicateManagementPanel() {
  const { t: i18nAttribute } = useAttributeI18n();
  const [groups, setGroups] = useState<DuplicateGroupResponse[]>([]);
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [merging, setMerging] = useState('');
  const [error, setError] = useState('');
  const [lastOperation, setLastOperation] = useState<LibraryOperationResponse | null>(null);
  const toast = useToast();

  async function load() {
    setLoading(true);
    setError('');
    try {
      const data = await apiV2Request<Page_DuplicateGroupResponse_>('/api/v2/catalog/duplicates');
      setGroups(data.items);
      setTargets(Object.fromEntries(data.items.map((group) => [group.id, group.works[0]?.id ?? ''])));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取重复项失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function merge(group: DuplicateGroupResponse) {
    const targetWorkId = targets[group.id];
    if (!targetWorkId) return;
    setMerging(group.id);
    setError('');
    try {
      const operation = await apiV2Request<LibraryOperationResponse>(
        '/api/v2/catalog/duplicates/merge',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ targetWorkId, sourceWorkIds: group.works.filter((work) => work.id !== targetWorkId).map((work) => work.id) })
        }
      );
      setLastOperation(operation);
      toast.success(
        i18nAttribute('重复项已合并'),
        i18nAttribute('已合并 {count} 个源作品，可在当前会话中撤销。', {
          count: operation.affectedWorks
        })
      );
      await load();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '合并重复项失败';
      setError(message);
      toast.error('合并失败', message);
    } finally {
      setMerging('');
    }
  }

  async function undo() {
    if (!lastOperation) return;
    try {
      await apiV2Request<LibraryOperationResponse>(
        `/api/v2/catalog/operations/${lastOperation.id}/undo`,
        { method: 'POST' }
      );
      toast.success(i18nAttribute('已撤销合并'));
      setLastOperation(null);
      await load();
    } catch (reason) {
      toast.error('撤销失败', reason instanceof Error ? reason.message : '撤销失败');
    }
  }

  if (loading) return <div className="flex min-h-48 items-center justify-center text-sm text-[#817B75]"><Loader2 size={17} className="mr-2 animate-spin" /><I18nText>正在分析重复作品…</I18nText></div>;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 rounded-2xl border border-black/[0.07] bg-white/60 p-5">
        <div>
          <h2 className="text-base font-semibold text-[#2C2926]"><I18nText>重复作品治理</I18nText></h2>
          <p className="mt-1 text-sm leading-6 text-[#817B75]"><I18nText>按规范化后的标题与作者识别候选。合并只移动版本、进度与书架关系，不删除源文件。</I18nText></p>
        </div>
        <Badge tone={groups.length ? 'amber' : 'green'}>{groups.length} <I18nText>组待处理</I18nText></Badge>
      </div>

      {lastOperation?.undoAvailable ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <span className="flex items-center gap-2"><CheckCircle2 size={16} />{i18nAttribute('已合并 {count} 个源作品，可在当前会话中撤销。', { count: lastOperation.affectedWorks })}</span>
          <Button variant="secondary" icon={RotateCcw} onClick={() => void undo()}><I18nText>撤销</I18nText></Button>
        </div>
      ) : null}
      {error ? <div className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      {groups.length === 0 ? (
        <div className="flex min-h-56 flex-col items-center justify-center rounded-2xl border border-dashed border-black/[0.1] bg-white/40 text-center">
          <Search size={24} className="text-[#A49E98]" />
          <div className="mt-3 font-medium text-[#3B3733]"><I18nText>没有发现重复作品</I18nText></div>
          <p className="mt-1 text-sm text-[#8A847E]"><I18nText>导入新版本或修改标题、作者后，这里会自动重新计算。</I18nText></p>
        </div>
      ) : groups.map((group) => (
        <section key={group.id} className="rounded-2xl border border-black/[0.07] bg-white/65 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold text-[#302D2A]">{group.works[0]?.title ?? i18nAttribute("重复作品")}</div>
              <div className="mt-1 text-xs text-[#8A847E]">
                {group.reasons.map((reason) => reason === 'NORMALIZED_TITLE'
                  ? i18nAttribute('标题一致')
                  : reason === 'NORMALIZED_AUTHOR'
                    ? i18nAttribute('作者一致')
                    : i18nAttribute('相似元数据')).join(i18nAttribute('；'))}
                <I18nText> · 匹配度 </I18nText>{Math.round(group.confidence * 100)}%
              </div>
            </div>
            <Button icon={GitMerge} loading={merging === group.id} loadingText={i18nAttribute("合并中")} onClick={() => void merge(group)}><I18nText>合并为主作品</I18nText></Button>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {group.works.map((work) => (
              <label key={work.id} className={`flex cursor-pointer gap-3 rounded-xl border p-4 transition ${targets[group.id] === work.id ? 'border-[#EEA58F] bg-[#FFF5F1]' : 'border-black/[0.07] bg-white hover:bg-[#FBF8F5]'}`}>
                <input type="radio" name={group.id} value={work.id} checked={targets[group.id] === work.id} onChange={() => setTargets((current) => ({ ...current, [group.id]: work.id }))} className="mt-1 accent-[#EF4D2F]" />
                <span className="min-w-0">
                  <span className="block font-medium text-[#302D2A]">{work.title}</span>
                  <span className="mt-1 block text-sm text-[#746E68]">{work.author || i18nAttribute('未知作者')} · {work.mediaType}</span>
                  <span className="mt-2 flex flex-wrap gap-1.5">{workTags(work).slice(0, 4).map((tag) => <Badge key={tag}>{tag}</Badge>)}</span>
                  {targets[group.id] === work.id ? <span className="mt-3 block text-xs font-medium text-[#D34B32]"><I18nText>保留此记录的标题、封面与基础信息</I18nText></span> : null}
                </span>
              </label>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
