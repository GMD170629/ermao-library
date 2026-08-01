'use client';

import { ArrowLeft, BookOpen, CheckCircle2, Download, Edit3, Headphones, Images, LoaderCircle, RefreshCw, Scissors, Trash2, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Cover } from '../../components/book/cover';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useToast } from '../../components/ui/feedback';
import type { MediaKind, VolumeResource, WorkDetailTabKey, WorkView } from '../../types/work';
import { I18nText } from '@/i18n/provider';
import { useI18n } from '@/i18n/provider';
import { deleteVolume, fetchWork, runVolumeAction, updateVolume } from './api/client';
import { detailTabsForBook, formatDuration, isWorkDetailTabKey, resolvedDetailTab, selectedVolumeForDetailTab, volumesForDetailTab, workDetailTabHref } from './work-detail-tabs';

type VolumeForm = Readonly<{
  title: string;
  volumeIndex: string;
  sortOrder: string;
  publisher: string;
  language: string;
  isbn: string;
  identifier: string;
  narrator: string;
}>;

function formForVolume(volume: VolumeResource): VolumeForm {
  return {
    title: volume.title,
    volumeIndex: volume.volumeIndex === null ? '' : String(volume.volumeIndex),
    sortOrder: String(volume.sortOrder),
    publisher: volume.publisher ?? '',
    language: volume.language ?? '',
    isbn: volume.isbn ?? '',
    identifier: volume.identifier ?? '',
    narrator: volume.narrator ?? ''
  };
}

function readerHref(volume: VolumeResource, mediaKind: MediaKind): string {
  return mediaKind === 'AUDIOBOOK'
    ? `/listen/${encodeURIComponent(volume.id)}`
    : `/reader/${encodeURIComponent(volume.id)}`;
}

function formatLabel(volume: VolumeResource): string {
  const details = [volume.format, volume.publisher, volume.language, volume.narrator].filter(Boolean);
  return details.join(' · ');
}

function VolumeCard({
  work,
  mediaKind,
  volume,
  selected,
  onSelect,
  onRefresh
}: {
  work: WorkView;
  mediaKind: MediaKind;
  volume: VolumeResource;
  selected: boolean;
  onSelect: () => void;
  onRefresh: () => Promise<void>;
}) {
  const router = useRouter();
  const feedback = useToast();
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<VolumeForm>(() => formForVolume(volume));
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => setForm(formForVolume(volume)), [volume]);

  const run = useCallback(async (key: string, action: () => Promise<void>, success: string) => {
    setBusy(key);
    try {
      await action();
      feedback.success(success);
      await onRefresh();
      return true;
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
      return false;
    } finally {
      setBusy(null);
    }
  }, [feedback, onRefresh, t]);

  const save = async () => {
    const saved = await run('save', () => updateVolume(work.id, volume.id, {
      title: form.title.trim(),
      volumeIndex: form.volumeIndex.trim() ? Number(form.volumeIndex) : null,
      sortOrder: Number(form.sortOrder),
      publisher: form.publisher.trim() || null,
      language: form.language.trim() || null,
      isbn: form.isbn.trim() || null,
      identifier: form.identifier.trim() || null,
      narrator: form.narrator.trim() || null
    }), '卷册信息已保存');
    if (saved) setEditing(false);
  };

  const remove = async () => {
    const confirmed = await feedback.confirm({
      title: '删除卷册',
      description: '将删除该卷册及其阅读进度、书签和任务。其他卷册会保留。',
      confirmLabel: '删除',
      tone: 'danger'
    });
    if (!confirmed) return;
    await run('delete', () => deleteVolume(work.id, volume.id), '卷册已删除');
  };

  return (
    <article className={cn('rounded-2xl border bg-white p-4 transition', selected ? 'border-orange-300 shadow-sm' : 'border-stone-200')}>
      <button type="button" onClick={onSelect} className="w-full text-left">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 data-i18n-skip className="truncate font-semibold text-stone-950">{volume.title}</h3>
            <p data-i18n-skip className="mt-1 truncate text-xs text-stone-500">{formatLabel(volume)}</p>
          </div>
          {volume.progress >= 100 ? <CheckCircle2 size={18} className="shrink-0 text-emerald-600" /> : <span className="shrink-0 text-sm tabular-nums text-stone-500">{Math.round(volume.progress)}%</span>}
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-stone-100">
          <div className="h-full rounded-full bg-[#ff4f2a]" style={{ width: `${Math.max(0, Math.min(100, volume.progress))}%` }} />
        </div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500">
          {volume.volumeIndex !== null ? <span>{t('卷号 {value0}', { value0: volume.volumeIndex })}</span> : null}
          {volume.pageCount ? <span>{t('{value0} 页', { value0: volume.pageCount })}</span> : null}
          {volume.chapterCount ? <span>{t('{value0} 章', { value0: volume.chapterCount })}</span> : null}
          {volume.durationMs ? <span data-i18n-skip>{formatDuration(volume.durationMs)}</span> : null}
          {volume.derivedFromVolumeId ? <span><I18nText>派生卷册</I18nText></span> : null}
        </div>
      </button>

      {selected ? (
        <div className="mt-4 flex flex-wrap gap-2 border-t border-stone-100 pt-4">
          <Button icon={mediaKind === 'AUDIOBOOK' ? Headphones : mediaKind === 'COMIC' ? Images : BookOpen} onClick={() => router.push(readerHref(volume, mediaKind))} disabled={!volume.readable}>
            {mediaKind === 'AUDIOBOOK' ? '播放' : '阅读'}
          </Button>
          <Button variant="secondary" icon={Download} onClick={() => { window.location.href = `/api/volumes/${encodeURIComponent(volume.id)}/file`; }}>
            下载
          </Button>
          <Button variant="ghost" icon={Edit3} onClick={() => setEditing(true)}>编辑卷册</Button>
          {volume.conversionAvailable ? <Button variant="ghost" icon={RefreshCw} loading={busy === 'convert'} onClick={() => void run('convert', () => runVolumeAction(work.id, volume.id, 'convert'), '已创建或刷新派生卷册')}>转换为 EPUB</Button> : null}
          <Button variant="ghost" icon={Scissors} loading={busy === 'split'} onClick={() => void run('split', () => runVolumeAction(work.id, volume.id, 'split', { title: `${work.title}（${volume.title}）`, author: work.author, copyShelves: true }), '卷册已拆分为新作品')}>拆分为作品</Button>
          <Button variant="danger" icon={Trash2} loading={busy === 'delete'} onClick={() => void remove()}>删除卷册</Button>
        </div>
      ) : null}

      {editing ? (
        <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/45 md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('编辑卷册')}>
          <div className="w-full max-w-xl rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
            <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>编辑卷册</I18nText></h2><button type="button" onClick={() => setEditing(false)} aria-label={t('关闭')}><X size={20} /></button></div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>卷册名称</I18nText><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>卷号（可选且可重复）</I18nText><input inputMode="decimal" value={form.volumeIndex} onChange={(event) => setForm({ ...form, volumeIndex: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>排序</I18nText><input inputMode="numeric" value={form.sortOrder} onChange={(event) => setForm({ ...form, sortOrder: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>出版社</I18nText><input value={form.publisher} onChange={(event) => setForm({ ...form, publisher: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>语言</I18nText><input value={form.language} onChange={(event) => setForm({ ...form, language: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>ISBN</I18nText><input value={form.isbn} onChange={(event) => setForm({ ...form, isbn: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>标识符</I18nText><input value={form.identifier} onChange={(event) => setForm({ ...form, identifier: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              {mediaKind === 'AUDIOBOOK' ? <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>朗读者</I18nText><input value={form.narrator} onChange={(event) => setForm({ ...form, narrator: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label> : null}
            </div>
            <div className="mt-6 flex justify-end gap-2"><Button variant="secondary" onClick={() => setEditing(false)}>取消</Button><Button loading={busy === 'save'} onClick={() => void save()}>保存</Button></div>
          </div>
        </div>
      ) : null}
    </article>
  );
}

export function BookDetailPage({ bookId }: { bookId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const feedback = useToast();
  const { t } = useI18n();
  const [work, setWork] = useState<WorkView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    setLoading(true);
    void fetchWork(bookId, controller.signal).then((next) => {
      if (!disposed) setWork(next);
    }).catch((reason) => {
      if (!disposed) setError(reason instanceof Error ? reason.message : t('读取作品失败'));
    }).finally(() => {
      if (!disposed) setLoading(false);
    });
    return () => { disposed = true; controller.abort(); };
  }, [bookId, t]);

  const requestedTab = isWorkDetailTabKey(searchParams.get('detailTab')) ? searchParams.get('detailTab') as WorkDetailTabKey : null;
  const requestedVolumeId = searchParams.get('volumeId')?.trim() || null;
  const tab = work ? resolvedDetailTab(work, requestedTab) : 'STRUCTURE';
  const selectedVolume = work ? selectedVolumeForDetailTab(work, tab, requestedVolumeId) : null;
  const tabs = useMemo(() => work ? detailTabsForBook(work) : [], [work]);
  const volumes = useMemo(() => work ? volumesForDetailTab(work, tab) : [], [tab, work]);

  const selectTab = (next: WorkDetailTabKey) => {
    if (!work) return;
    const nextVolume = selectedVolumeForDetailTab(work, next, work.continueVolumeId);
    router.replace(workDetailTabHref(work.id, next, nextVolume?.id));
  };

  const selectVolume = (volume: VolumeResource, mediaKind: MediaKind) => {
    if (!work) return;
    router.replace(workDetailTabHref(work.id, mediaKind, volume.id));
  };

  if (loading && !work) return <div className="flex min-h-[60vh] items-center justify-center"><LoaderCircle className="animate-spin text-[#ff4f2a]" /></div>;
  if (!work) return <div className="mx-auto max-w-lg p-8 text-center"><p className="text-stone-600">{error || t('作品不存在')}</p><Button className="mt-4" onClick={() => router.push('/library')}>返回书库</Button></div>;

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8 md:py-10">
      <button type="button" onClick={() => router.push('/library')} className="mb-6 inline-flex items-center gap-2 text-sm text-stone-600 hover:text-stone-950"><ArrowLeft size={17} /><I18nText>返回书库</I18nText></button>
      <section className="grid gap-6 md:grid-cols-[180px_minmax(0,1fr)]">
        <Cover book={{ id: work.id, title: work.title, author: work.author, coverUrl: work.coverUrl, gradient: work.gradient, coverStatus: work.coverStatus }} className="mx-auto aspect-[2/3] w-[160px] md:mx-0 md:w-[180px]" size="large" priority />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">{work.completed ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"><CheckCircle2 size={14} /><I18nText>已完成</I18nText></span> : null}</div>
          <h1 data-i18n-skip className="mt-2 text-3xl font-bold tracking-tight text-stone-950">{work.title}</h1>
          <p data-i18n-skip className="mt-2 text-stone-600">{work.author}</p>
          {work.description ? <p data-i18n-skip className="mt-5 max-w-3xl whitespace-pre-wrap text-sm leading-7 text-stone-600">{work.description}</p> : <p className="mt-5 text-sm text-stone-400"><I18nText>暂无简介</I18nText></p>}
          {error ? <p className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
        </div>
      </section>

      <nav className="mt-10 flex gap-2 overflow-x-auto border-b border-stone-200" aria-label={t('作品媒介')}>
        {tabs.map((item) => <button key={item.key} type="button" onClick={() => selectTab(item.key)} className={cn('min-h-11 shrink-0 border-b-2 px-4 text-sm font-medium', tab === item.key ? 'border-[#ff4f2a] text-[#d94322]' : 'border-transparent text-stone-500 hover:text-stone-900')}>{t(item.label)}</button>)}
      </nav>

      {tab === 'STRUCTURE' ? (
        <section className="mt-6 space-y-7">
          {work.mediaVersions.map((mediaVersion) => (
            <div key={mediaVersion.id}>
              <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-stone-950">{t(mediaVersion.mediaKind === 'EBOOK' ? '电子书' : mediaVersion.mediaKind === 'COMIC' ? '漫画' : '有声书')}</h2><span className="text-sm text-stone-500">{t('{value0} 个卷册', { value0: mediaVersion.volumes.length })}</span></div>
              <div className="grid gap-3 sm:grid-cols-2">{[...mediaVersion.volumes].sort((left, right) => left.sortOrder - right.sortOrder || left.id.localeCompare(right.id)).map((volume) => <VolumeCard key={volume.id} work={work} mediaKind={mediaVersion.mediaKind} volume={volume} selected={selectedVolume?.id === volume.id} onSelect={() => selectVolume(volume, mediaVersion.mediaKind)} onRefresh={async () => { try { setWork(await fetchWork(bookId)); } catch (reason) { feedback.error(reason instanceof Error ? reason.message : t('刷新失败')); } }} />)}</div>
            </div>
          ))}
        </section>
      ) : (
        <section className="mt-6">
          {volumes.length ? <div className="grid gap-3 sm:grid-cols-2">{volumes.map((volume) => <VolumeCard key={volume.id} work={work} mediaKind={tab} volume={volume} selected={selectedVolume?.id === volume.id} onSelect={() => selectVolume(volume, tab)} onRefresh={async () => { try { setWork(await fetchWork(bookId)); } catch (reason) { feedback.error(reason instanceof Error ? reason.message : t('刷新失败')); } }} />)}</div> : <div className="rounded-2xl border border-dashed border-stone-300 p-10 text-center text-sm text-stone-500"><I18nText>该媒介还没有可见卷册</I18nText></div>}
        </section>
      )}
    </main>
  );
}
