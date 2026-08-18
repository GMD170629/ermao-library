'use client';

import { CheckCircle2, ChevronLeft, ChevronRight, GitMerge, Loader2, RotateCcw, Search } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { useToast } from '../../components/ui/feedback';
import type { WorkView } from '../../types/work';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type DuplicateGroup = { id: string; confidence: number; reasons: string[]; works: WorkView[] };
type ApiPayload<T> = { ok: boolean; data?: T; error?: { message: string } };

async function payload<T>(response: Response, fallback: string) {
  const result = await response.json().catch(() => null) as ApiPayload<T> | null;
  if (!response.ok || !result?.ok) throw new Error(result?.error?.message ?? fallback);
  return result.data as T;
}

export function DuplicateManagementPanel() {
  const { t: i18nAttribute } = useAttributeI18n();
  const [groups, setGroups] = useState<DuplicateGroup[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [merging, setMerging] = useState('');
  const [error, setError] = useState('');
  const [lastOperation, setLastOperation] = useState<{ id: string; summary: string; undoAvailable: boolean } | null>(null);
  const toast = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ page: String(page), pageSize: '20' });
      const data = await payload<{ groups: DuplicateGroup[]; page: number; total: number; totalPages: number }>(await fetch(`/api/library/duplicates?${params}`), '读取重复项失败');
      setGroups(data.groups);
      setPage(data.page);
      setTotal(data.total);
      setTotalPages(Math.max(1, data.totalPages));
      setTargets(Object.fromEntries(data.groups.map((group) => [group.id, group.works[0]?.id ?? ''])));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取重复项失败');
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { void load(); }, [load]);

  async function merge(group: DuplicateGroup) {
    const targetWorkId = targets[group.id];
    if (!targetWorkId) return;
    setMerging(group.id);
    setError('');
    try {
      const data = await payload<{ operation: { id: string; summary: string; undoAvailable: boolean } }>(
        await fetch('/api/library/duplicates/merge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ targetWorkId, sourceWorkIds: group.works.filter((work) => work.id !== targetWorkId).map((work) => work.id) })
        }),
        '合并重复项失败'
      );
      setLastOperation(data.operation);
      toast.success('重复项已合并', data.operation.summary);
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
      await payload(await fetch(`/api/library/operations/${lastOperation.id}/undo`, { method: 'POST' }), '撤销失败');
      toast.success('已撤销合并');
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
          <p className="mt-1 text-sm leading-6 text-[#817B75]"><I18nText>按规范化后的标题与作者识别候选。合并只移动媒介版本、卷册、进度与书架关系，不删除源文件。</I18nText></p>
        </div>
        <Badge tone={total ? 'amber' : 'green'}>{total} <I18nText>组待处理</I18nText></Badge>
      </div>

      {lastOperation?.undoAvailable ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <span className="flex items-center gap-2"><CheckCircle2 size={16} />{lastOperation.summary}</span>
          <Button variant="secondary" icon={RotateCcw} onClick={() => void undo()}><I18nText>撤销</I18nText></Button>
        </div>
      ) : null}
      {error ? <div className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      {groups.length === 0 ? (
        <div className="flex min-h-56 flex-col items-center justify-center rounded-2xl border border-dashed border-black/[0.1] bg-white/40 text-center">
          <Search size={24} className="text-[#A49E98]" />
          <div className="mt-3 font-medium text-[#3B3733]"><I18nText>没有发现重复作品</I18nText></div>
          <p className="mt-1 text-sm text-[#8A847E]"><I18nText>导入新卷册或修改标题、作者后，这里会自动重新计算。</I18nText></p>
        </div>
      ) : groups.map((group) => (
        <section key={group.id} className="rounded-2xl border border-black/[0.07] bg-white/65 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold text-[#302D2A]">{group.works[0]?.title ?? i18nAttribute("重复作品")}</div>
              <div className="mt-1 text-xs text-[#8A847E]">{group.reasons.join('；')} <I18nText>· 匹配度 </I18nText>{Math.round(group.confidence * 100)}%</div>
            </div>
            <Button icon={GitMerge} loading={merging === group.id} loadingText={i18nAttribute("合并中")} onClick={() => void merge(group)}><I18nText>合并为主作品</I18nText></Button>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {group.works.map((work) => (
              <label key={work.id} className={`flex cursor-pointer gap-3 rounded-xl border p-4 transition ${targets[group.id] === work.id ? 'border-[#EEA58F] bg-[#FFF5F1]' : 'border-black/[0.07] bg-white hover:bg-[#FBF8F5]'}`}>
                <input type="radio" name={group.id} value={work.id} checked={targets[group.id] === work.id} onChange={() => setTargets((current) => ({ ...current, [group.id]: work.id }))} className="mt-1 accent-[#EF4D2F]" />
                <span className="min-w-0">
                  <span className="block font-medium text-[#302D2A]">{work.title}</span>
                  <span className="mt-1 block text-sm text-[#746E68]">{work.author} · {work.versions.flatMap((version) => version.volumes).length} <I18nText>个卷册</I18nText></span>
                  <span className="mt-2 flex flex-wrap gap-1.5">{work.tags.slice(0, 4).map((tag) => <Badge key={tag}>{tag}</Badge>)}</span>
                  {targets[group.id] === work.id ? <span className="mt-3 block text-xs font-medium text-[#D34B32]"><I18nText>保留此记录的标题、封面与基础信息</I18nText></span> : null}
                </span>
              </label>
            ))}
          </div>
        </section>
      ))}

      {totalPages > 1 ? (
        <div className="flex items-center justify-center gap-3" aria-label={i18nAttribute("重复作品治理")}>
          <button type="button" disabled={page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40" aria-label={i18nAttribute("上一页")}><ChevronLeft size={16} /></button>
          <span className="text-sm tabular-nums text-[#817B75]">{i18nAttribute("第 {value0} / {value1} 页", { value0: page, value1: totalPages })}</span>
          <button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((current) => Math.min(totalPages, current + 1))} className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#DEDAD4] bg-white transition hover:bg-[#F7F4F0] disabled:opacity-40" aria-label={i18nAttribute("下一页")}><ChevronRight size={16} /></button>
        </div>
      ) : null}
    </div>
  );
}
