'use client';

import { ArrowLeft, BookOpen, Check, CheckCircle2, ChevronDown, ChevronRight, ChevronUp, Database, Download, Edit3, Ellipsis, Headphones, ImageUp, Images, LoaderCircle, RefreshCw, RotateCcw, Send, Settings2, X, type LucideIcon } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useId, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { Cover } from '../../components/book/cover';
import { CoverReadingProgress, coverReadingProgressState } from '../../components/book/cover-reading-progress';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { ContextActionMenu, type ContextMenuPosition } from '../../components/ui/context-action-menu';
import { useToast } from '../../components/ui/feedback';
import { useAppSession } from '../../components/layout/app-session-context';
import { Select } from '../../components/ui/select';
import type { MediaKind, ReaderType, VersionResource, VolumeResource, WorkView } from '../../types/work';
import { I18nText } from '@/i18n/provider';
import { useI18n } from '@/i18n/provider';
import { downloadVolumeArchive, fetchAllVersionVolumes, fetchEbookChapterDetail, fetchWork, reclassifyVolume, regenerateWorkCover, runVolumeBatchAction, undoLibraryOperation, updateVolume, updateVolumeReadingStatus, uploadWorkCover, volumeFileDownloadUrl } from './api/client';
import { useVolumeWallSelection } from './application/use-volume-wall-selection';
import { displayVolumeNumber, formatDuration, mediaKindOfVolume, selectedVolumeForWork, shouldShowVersionHeadings, versionDisplayTitle, workDetailHref, workDetailReturnHref } from './work-detail';
import { smallVolumeCoverUrl } from './volume-cover-url';
import { KindleSendModal } from './kindle-send-modal';
import { MetadataLookupModal } from './metadata-lookup-modal';
import { bookActionIds, type BookActionId } from './model/book-action-menu';
import { CHAPTER_DETAIL_PAGE_SIZE, singleVolumeEbook, type EbookChapterDetail } from './model/chapter-detail';
import { currentPositionLabel } from './model/current-position-label';
import { structureFileLabel } from './model/structure-file-label';
import { structureVolumeList } from './model/structure-volume-list';
import { volumeActionAvailability, type VolumeActionId } from './model/volume-action-menu';
import { SingleVolumeChapterList } from './ui/single-volume-chapter-list';
import { WorkMetadataEditor } from './ui/work-metadata-editor';

type VolumeForm = Readonly<{
  publisher: string;
  language: string;
  isbn: string;
  identifier: string;
  narrator: string;
}>;

const BOOK_ACTION_DETAILS: Record<BookActionId, { label: string; icon: LucideIcon }> = {
  edit: { label: '编辑信息', icon: Edit3 },
  metadata: { label: '元数据识别', icon: Database },
  'upload-cover': { label: '上传自定义封面', icon: ImageUp },
  'regenerate-cover': { label: '重新生成封面', icon: RefreshCw },
  download: { label: '下载当前版本', icon: Download },
  kindle: { label: '发送到 Kindle', icon: Send }
};

const VOLUME_ACTION_DETAILS: Record<VolumeActionId, { label: string; description: string; icon: LucideIcon }> = {
  download: { label: '下载', description: '下载所选卷册的源文件', icon: Download },
  edit: { label: '编辑', description: '修改卷册元数据', icon: Edit3 },
  'set-media-kind': { label: '设置媒体类型', description: '将卷册归类为其他媒体类型', icon: Settings2 },
  'set-ebook': { label: '设置为电子书', description: '使用电子书方式管理和阅读', icon: BookOpen },
  'set-comic': { label: '设置为漫画', description: '使用漫画方式管理和阅读', icon: Images },
  'set-audiobook': { label: '设置为有声书', description: '使用有声书方式管理和收听', icon: Headphones }
};

function formForVolume(volume: VolumeResource): VolumeForm {
  return {
    publisher: volume.publisher ?? '',
    language: volume.language ?? '',
    isbn: volume.isbn ?? '',
    identifier: volume.identifier ?? '',
    narrator: volume.narrator ?? ''
  };
}

function readerHref(volume: VolumeResource): string {
  return volume.readerType === 'audio'
    ? `/listen/${encodeURIComponent(volume.id)}`
    : `/reader/${encodeURIComponent(volume.id)}`;
}

function formatLabel(volume: VolumeResource): string {
  const details = [volume.format, volume.publisher, volume.language, volume.narrator].filter(Boolean);
  return details.join(' · ');
}

function consumptionCopy(readerType: ReaderType) {
  if (readerType === 'audio') return { progress: '收听进度', position: '当前收听', start: '开始听', resume: '继续听', status: '收听状态' } as const;
  if (readerType === 'comic') return { progress: '阅读进度', position: '当前卷册', start: '开始看', resume: '继续看', status: '阅读状态' } as const;
  return { progress: '阅读进度', position: '当前位置', start: '开始阅读', resume: '继续阅读', status: '阅读状态' } as const;
}

function VolumeWallCard({
  work,
  volume,
  position,
  canManage,
  selected,
  onBeginSelection,
  onEnterSelection,
  onOpenContextMenu
}: {
  work: WorkView;
  volume: VolumeResource;
  position: number;
  canManage: boolean;
  selected: boolean;
  onBeginSelection: (event: ReactMouseEvent<HTMLButtonElement>) => void;
  onEnterSelection: () => void;
  onOpenContextMenu: (position: ContextMenuPosition, anchor: HTMLButtonElement) => void;
}) {
  const router = useRouter();
  const { t } = useI18n();
  const number = displayVolumeNumber(volume, position);
  const progress = coverReadingProgressState(volume.progress);
  const openVolume = () => {
    if (volume.readable) router.push(readerHref(volume));
  };
  return (
    <button
      type="button"
      data-volume-wall-card="true"
      onMouseDown={(event) => { if (canManage) onBeginSelection(event); }}
      onMouseEnter={() => { if (canManage) onEnterSelection(); }}
      onClick={() => {
        if (!canManage) openVolume();
      }}
      onDoubleClick={() => { if (canManage) openVolume(); }}
      onContextMenu={(event) => {
        if (!canManage) return;
        event.preventDefault();
        onOpenContextMenu({ x: event.clientX, y: event.clientY }, event.currentTarget);
      }}
      onKeyDown={(event) => {
        if (!canManage || (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10'))) return;
        event.preventDefault();
        const bounds = event.currentTarget.getBoundingClientRect();
        onOpenContextMenu({ x: bounds.left + Math.min(bounds.width, 28), y: bounds.top + Math.min(bounds.height, 28) }, event.currentTarget);
      }}
      aria-label={progress.visible
        ? t(volume.readerType === 'audio' ? '第 {value0} 卷，收听进度 {value1}%' : '第 {value0} 卷，阅读进度 {value1}%', {
            value0: number,
            value1: progress.roundedValue
          })
        : t('第 {value0} 卷', { value0: number })}
      aria-pressed={canManage ? selected : undefined}
      className={cn('group min-w-0 text-left', !volume.readable && !canManage && 'cursor-not-allowed opacity-50')}
    >
      <div className={cn('relative overflow-hidden rounded-xl bg-stone-100 shadow-sm transition group-hover:-translate-y-0.5 group-hover:shadow-md group-focus-visible:outline group-focus-visible:outline-2 group-focus-visible:outline-offset-2 group-focus-visible:outline-[#ff4f2a]', selected && 'ring-2 ring-[#ff4f2a] ring-offset-2')}>
        <Cover book={{ id: volume.id, title: volume.title, author: work.author, coverUrl: smallVolumeCoverUrl(volume.id, volume.coverUrl), gradient: work.gradient, coverStatus: '' }} className="aspect-[2/3] w-full rounded-none" size="small" />
        <span className="absolute left-2 top-2 rounded-full bg-white/90 px-2 py-0.5 text-[11px] tabular-nums text-stone-600 shadow-sm">{String(number).padStart(2, '0')}</span>
        {selected ? <span className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-full bg-[#ff4f2a] text-white shadow-sm" aria-hidden="true"><Check size={14} strokeWidth={3} /></span> : null}
        <CoverReadingProgress progress={volume.progress} surface="volume" />
      </div>
      <span data-i18n-skip className="mt-2 block line-clamp-2 text-sm font-medium leading-5 text-stone-900">{volume.title}</span>
    </button>
  );
}

function VolumeContextEditDialog({
  work,
  volume,
  onClose,
  onSaved
}: {
  work: WorkView;
  volume: VolumeResource | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const feedback = useToast();
  const { t } = useI18n();
  const [form, setForm] = useState<VolumeForm | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setForm(volume ? formForVolume(volume) : null);
  }, [volume]);

  if (!volume || !form) return null;
  const save = async () => {
    setSaving(true);
    try {
      await updateVolume(work.id, volume.id, {
        publisher: form.publisher.trim() || null,
        language: form.language.trim() || null,
        isbn: form.isbn.trim() || null,
        identifier: form.identifier.trim() || null,
        narrator: form.narrator.trim() || null
      });
      await onSaved();
      feedback.success(t('卷册信息已保存'));
      onClose();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setSaving(false);
    }
  };

  return <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/45 md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('编辑卷册')}>
    <div className="w-full max-w-xl rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>编辑卷册</I18nText></h2><button type="button" onClick={onClose} aria-label={t('关闭')}><X size={20} /></button></div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="text-sm text-stone-600"><I18nText>出版社</I18nText><input value={form.publisher} onChange={(event) => setForm({ ...form, publisher: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>语言</I18nText><input value={form.language} onChange={(event) => setForm({ ...form, language: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>ISBN</I18nText><input value={form.isbn} onChange={(event) => setForm({ ...form, isbn: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>标识符</I18nText><input value={form.identifier} onChange={(event) => setForm({ ...form, identifier: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        {volume.readerType === 'audio' ? <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>朗读者</I18nText><input value={form.narrator} onChange={(event) => setForm({ ...form, narrator: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label> : null}
      </div>
      <div className="mt-6 flex justify-end gap-2"><Button variant="secondary" onClick={onClose}><I18nText>取消</I18nText></Button><Button loading={saving} onClick={() => void save()}><I18nText>保存</I18nText></Button></div>
    </div>
  </div>;
}

function visibleVersionVolumes(version: VersionResource): VolumeResource[] {
  return version.volumes
    .filter((volume) => !volume.hidden)
    .sort((left, right) => left.sortOrder - right.sortOrder || left.id.localeCompare(right.id));
}

function classificationLabel(volume: VolumeResource): string {
  if (volume.classification.source === 'LIBRARY_RULE') return '来自书库规则';
  if (volume.classification.source === 'USER') return '手动设置';
  if (volume.classification.reason === 'COMIC_SUBJECT') return '自动识别 · 包含漫画主题';
  if (volume.classification.source === 'AUTO') return '自动识别 · 默认按电子书处理';
  return '自动识别 · 默认按电子书处理';
}

function volumeUnitLabel(volume: VolumeResource, translate: (source: string, values?: Record<string, string | number>) => string): string {
  if (volume.pageCount) return translate('{value0} 页', { value0: volume.pageCount });
  if (volume.chapterCount) return translate('{value0} 章', { value0: volume.chapterCount });
  if (volume.trackCount) return translate('{value0} 音轨', { value0: volume.trackCount });
  return '';
}

function StructureVersionCard({
  work,
  version,
  showHeading,
  managementMode,
  canManage,
  onLoadAll,
  onRefresh
}: {
  work: WorkView;
  version: VersionResource;
  showHeading: boolean;
  managementMode: boolean;
  canManage: boolean;
  onLoadAll: () => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const router = useRouter();
  const feedback = useToast();
  const { formatNumber, t } = useI18n();
  const [managedVolumeId, setManagedVolumeId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loadingAll, setLoadingAll] = useState(false);
  const volumeListId = useId();
  const volumes = visibleVersionVolumes(version);
  const { visibleVolumes, canToggle } = structureVolumeList(volumes, expanded, version.volumeCount);
  const firstReadableVolume = volumes.find((volume) => volume.readable) ?? null;
  const totalSizeBytes = version.sizeBytes;
  const sizeLabel = totalSizeBytes > 0
    ? totalSizeBytes >= 1024 ** 3
      ? `${formatNumber(totalSizeBytes / 1024 ** 3, { maximumFractionDigits: 1 })} GB`
      : `${formatNumber(totalSizeBytes / 1024 ** 2, { maximumFractionDigits: 1 })} MB`
    : null;

  const toggleVolumes = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setLoadingAll(true);
    try {
      if (volumes.length < version.volumeCount) await onLoadAll();
      setExpanded(true);
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('卷册加载失败'));
    } finally {
      setLoadingAll(false);
    }
  };

  return (
    <article className="rounded-2xl border border-stone-200 bg-white">
      <div className="flex flex-wrap items-center gap-4 p-4 sm:p-5">
        {showHeading ? <span className="inline-flex min-w-16 justify-center rounded-lg border border-orange-100 bg-orange-50 px-3 py-2 text-xs font-semibold text-amber-700">{t(versionDisplayTitle(version) ?? '默认版本')}</span> : null}
        <div className="min-w-[220px] flex-1">
          <div className="text-xs text-stone-500">
            {[sizeLabel, t('{value0} 个卷册', { value0: version.volumeCount })].filter(Boolean).join(' · ')}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" className="!min-h-9 !rounded-xl !px-3 !py-1.5" disabled={!firstReadableVolume} onClick={() => firstReadableVolume && router.push(readerHref(firstReadableVolume))}>
            {t(firstReadableVolume?.readerType === 'audio' ? '收听' : firstReadableVolume?.readerType === 'comic' ? '查看' : '阅读')}
          </Button>
        </div>
      </div>

      {volumes.length ? <div id={volumeListId} className="border-t border-stone-100 px-4 py-2 sm:px-5">
        {visibleVolumes.map((volume, index) => (
          <div key={volume.id} className="border-b border-stone-100 last:border-b-0">
            <div className="flex min-h-12 items-center gap-3 py-2">
              <span className="w-8 text-xs tabular-nums text-stone-400">{String(displayVolumeNumber(volume, index)).padStart(2, '0')}</span>
              <div className="min-w-0 flex-1">
                <span data-i18n-skip className="block truncate text-sm text-stone-800" title={volume.title}>{volume.title}</span>
                {volume.readerType !== 'audio' ? volume.files.map((file) => {
                  const label = structureFileLabel(volume.readerType, file.path);
                  return <span key={file.id} data-i18n-skip className="mt-0.5 block truncate text-xs text-stone-400" title={label}>{label}</span>;
                }) : null}
              </div>
              <span className="text-xs text-stone-400">{volumeUnitLabel(volume, t)}</span>
              {managementMode ? <div className="flex items-center gap-1">
                <button type="button" aria-expanded={managedVolumeId === volume.id} onClick={() => setManagedVolumeId((current) => current === volume.id ? null : volume.id)} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100" aria-label={t('编辑 {value0}', { value0: volume.title })}><Edit3 size={15} /></button>
              </div> : <button type="button" disabled={!volume.readable} onClick={() => router.push(readerHref(volume))} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100 disabled:opacity-30" aria-label={t('打开 {value0}', { value0: volume.title })}><ChevronRight size={16} /></button>}
            </div>
            {managementMode && managedVolumeId === volume.id ? <div className="pb-4 pt-2">
              <VolumeCard work={work} mediaKind={mediaKindOfVolume(volume)} volume={volume} canManage={canManage} onRefresh={onRefresh} />
            </div> : null}
          </div>
        ))}
        {canToggle ? <button
          type="button"
          aria-controls={volumeListId}
          aria-expanded={expanded}
          disabled={loadingAll}
          onClick={() => void toggleVolumes()}
          className="flex min-h-11 w-full items-center justify-center gap-1.5 rounded-lg text-sm font-medium text-stone-600 transition hover:bg-stone-50 hover:text-stone-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-200"
        >
          {loadingAll ? <LoaderCircle className="animate-spin" size={16} /> : expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          {loadingAll ? t('正在加载全部卷册…') : expanded ? t('收起卷册') : t('展开全部（共 {value0} 卷）', { value0: version.volumeCount })}
        </button> : null}
      </div> : <div className="border-t border-stone-100 px-5 py-3 text-sm text-stone-400"><I18nText>该版本还没有可见卷册</I18nText></div>}
    </article>
  );
}

function VolumeCard({
  work,
  mediaKind,
  volume,
  canManage,
  onRefresh
}: {
  work: WorkView;
  mediaKind: MediaKind;
  volume: VolumeResource;
  canManage: boolean;
  onRefresh: () => Promise<void>;
}) {
  const feedback = useToast();
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<VolumeForm>(() => formForVolume(volume));
  const [busy, setBusy] = useState<string | null>(null);
  const [targetMediaKind, setTargetMediaKind] = useState<MediaKind>(mediaKind);
  const [applyToVersion, setApplyToVersion] = useState(false);
  const [undoOperationId, setUndoOperationId] = useState<string | null>(null);

  useEffect(() => {
    setForm(formForVolume(volume));
    setTargetMediaKind(mediaKind);
    setApplyToVersion(false);
  }, [mediaKind, volume]);

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
    if (applyToVersion && targetMediaKind !== mediaKind) {
      const confirmed = await feedback.confirm({
        title: '修改此版本全部卷册的内容分类',
        description: '只调整内容分类，不改变文件、阅读进度、书签或阅读器。',
        confirmLabel: '继续修改'
      });
      if (!confirmed) return;
    }
    const saved = await run('save', () => updateVolume(work.id, volume.id, {
      publisher: form.publisher.trim() || null,
      language: form.language.trim() || null,
      isbn: form.isbn.trim() || null,
      identifier: form.identifier.trim() || null,
      narrator: form.narrator.trim() || null
    }).then(async () => {
      if (targetMediaKind === mediaKind) return;
      const operationId = await reclassifyVolume(work.id, volume.id, targetMediaKind, applyToVersion ? 'SAME_MEDIA_KIND' : 'VOLUME');
      setUndoOperationId(operationId);
    }), '卷册信息已保存');
    if (saved) setEditing(false);
  };

  return (
    <article className="rounded-2xl border border-orange-300 bg-white p-4 shadow-sm">
      <div className="w-full text-left">
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
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2 border-t border-stone-100 pt-4">
          {undoOperationId ? <Button variant="secondary" icon={RotateCcw} loading={busy === 'undo-classification'} onClick={() => void run('undo-classification', async () => { await undoLibraryOperation(undoOperationId); setUndoOperationId(null); }, '已撤销内容分类调整')}>撤销分类调整</Button> : null}
          {canManage ? <><Button variant="secondary" icon={Download} onClick={() => { window.location.href = volumeFileDownloadUrl(volume.id); }}>
            下载
          </Button>
          <Button variant="ghost" icon={Edit3} onClick={() => setEditing(true)}>编辑卷册</Button></> : null}
      </div>

      {editing ? (
        <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/45 md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('编辑卷册')}>
          <div className="w-full max-w-xl rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
            <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>编辑卷册</I18nText></h2><button type="button" onClick={() => setEditing(false)} aria-label={t('关闭')}><X size={20} /></button></div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>当前内容分类</I18nText><Select value={targetMediaKind} onChange={setTargetMediaKind} ariaLabel="当前内容分类" className="mt-1.5 w-full" options={[{ value: 'EBOOK', label: '电子书' }, { value: 'COMIC', label: '漫画' }, { value: 'AUDIOBOOK', label: '有声书' }]} /><span className="mt-1.5 block text-xs text-stone-500">{t(classificationLabel(volume))}</span>{volume.classification.suggestedMediaKind === 'COMIC' ? <button type="button" className="mt-2 rounded-lg bg-orange-50 px-2.5 py-1.5 text-xs font-medium text-orange-700" onClick={() => setTargetMediaKind('COMIC')}>{t('可能是漫画 · 改为漫画')}</button> : null}</label>
              <label className="flex items-center gap-2 text-sm text-stone-600 sm:col-span-2"><input type="checkbox" checked={applyToVersion} onChange={(event) => setApplyToVersion(event.target.checked)} />{t('同时应用到此版本全部 {value0} 个卷册', { value0: work.versions.find((version) => version.id === volume.versionId)?.volumeCount ?? 1 })}</label>
              <label className="text-sm text-stone-600"><I18nText>出版社</I18nText><input value={form.publisher} onChange={(event) => setForm({ ...form, publisher: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>语言</I18nText><input value={form.language} onChange={(event) => setForm({ ...form, language: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>ISBN</I18nText><input value={form.isbn} onChange={(event) => setForm({ ...form, isbn: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>标识符</I18nText><input value={form.identifier} onChange={(event) => setForm({ ...form, identifier: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              {volume.readerType === 'audio' ? <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>朗读者</I18nText><input value={form.narrator} onChange={(event) => setForm({ ...form, narrator: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label> : null}
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
  const session = useAppSession();
  const { t } = useI18n();
  const canManage = session?.authorization?.canManageSystem === true;
  const [work, setWork] = useState<WorkView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [managementMode, setManagementMode] = useState(false);
  const [readingStatusBusy, setReadingStatusBusy] = useState(false);
  const [topActionsOpen, setTopActionsOpen] = useState(false);
  const [editingMetadata, setEditingMetadata] = useState(false);
  const [metadataLookupOpen, setMetadataLookupOpen] = useState(false);
  const [kindleSendOpen, setKindleSendOpen] = useState(false);
  const [workActionBusy, setWorkActionBusy] = useState<string | null>(null);
  const [coverRevision, setCoverRevision] = useState(0);
  const [chapterPagination, setChapterPagination] = useState<{ volumeId: string | null; page: number }>({ volumeId: null, page: 1 });
  const [chapterDetailState, setChapterDetailState] = useState<{ volumeId: string; detail: EbookChapterDetail } | null>(null);
  const [chapterLoading, setChapterLoading] = useState(false);
  const [chapterError, setChapterError] = useState('');
  const [volumeMenuPosition, setVolumeMenuPosition] = useState<ContextMenuPosition | null>(null);
  const [volumeMenuAnchor, setVolumeMenuAnchor] = useState<HTMLButtonElement | null>(null);
  const [editingWallVolumeId, setEditingWallVolumeId] = useState<string | null>(null);
  const [volumeActionBusy, setVolumeActionBusy] = useState<VolumeActionId | null>(null);
  const topActionsRef = useRef<HTMLDivElement>(null);
  const coverInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!topActionsOpen) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (!topActionsRef.current?.contains(event.target as Node)) setTopActionsOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setTopActionsOpen(false);
    };
    document.addEventListener('mousedown', closeOnOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeOnOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [topActionsOpen]);

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

  const requestedVolumeId = searchParams.get('volumeId')?.trim() || null;
  const returnHref = workDetailReturnHref(searchParams.get('returnTo'));
  const selectedVolume = work ? selectedVolumeForWork(work, requestedVolumeId) : null;
  const selectedVersion = work && selectedVolume
    ? work.versions.find((version) => version.id === selectedVolume.versionId) ?? work.versions[0] ?? null
    : work?.versions[0] ?? null;
  const showVersionHeadings = work ? shouldShowVersionHeadings(work) : false;
  const allVolumes = useMemo(() => work ? work.versions.flatMap((version) => visibleVersionVolumes(version)) : [], [work]);
  const singleEbookVolume = singleVolumeEbook(allVolumes);
  const wallVolumeIds = useMemo(() => allVolumes.map((volume) => volume.id), [allVolumes]);
  const wallSelection = useVolumeWallSelection({
    enabled: canManage && !singleEbookVolume,
    scopeKey: work?.id ?? '',
    volumeIds: wallVolumeIds
  });
  const chapterPage = singleEbookVolume && chapterPagination.volumeId === singleEbookVolume.id ? chapterPagination.page : 1;
  const chapterDetail = singleEbookVolume && chapterDetailState?.volumeId === singleEbookVolume.id ? chapterDetailState.detail : null;
  const activeProgress = selectedVolume?.progress ?? 0;
  const activeCopy = selectedVolume ? consumptionCopy(selectedVolume.readerType) : null;
  const activeReaderHref = selectedVolume?.readable ? readerHref(selectedVolume) : null;
  const readingStatus = activeProgress >= 100 ? 'FINISHED' : activeProgress > 0 ? 'READING' : 'UNREAD';
  const workActions = bookActionIds({
    canManage,
    hasDownload: Boolean(selectedVersion),
    kindleSendAvailable: selectedVolume?.kindleSendAvailable === true
  });
  const currentWorkId = work?.id;

  const loadAllVolumes = useCallback(async (versionId: string, signal?: AbortSignal) => {
    if (!currentWorkId) return [];
    const nextVolumes = await fetchAllVersionVolumes(currentWorkId, versionId, signal);
    setWork((current) => current ? {
      ...current,
      versions: current.versions.map((version) => version.id === versionId
        ? { ...version, volumes: nextVolumes, volumeCount: nextVolumes.length }
        : version)
    } : current);
    return nextVolumes;
  }, [currentWorkId]);

  const selectedWallVolumes = useMemo(() => allVolumes.filter((volume) => wallSelection.selectedIds.has(volume.id)), [allVolumes, wallSelection.selectedIds]);
  const selectedWallVolume = selectedWallVolumes.length === 1 ? selectedWallVolumes[0] ?? null : null;
  const wallVolumeActions = volumeActionAvailability({
    canManage,
    readable: selectedWallVolumes.length > 0 && selectedWallVolumes.every((volume) => volume.readable),
    mediaKind: selectedWallVolume ? mediaKindOfVolume(selectedWallVolume) : 'EBOOK',
    selectionCount: selectedWallVolumes.length
  });

  useEffect(() => {
    setVolumeMenuPosition(null);
    setVolumeMenuAnchor(null);
  }, [selectedVersion?.id]);

  useEffect(() => {
    if (!selectedVersion || selectedVersion.volumes.length >= selectedVersion.volumeCount) return;
    const controller = new AbortController();
    void loadAllVolumes(selectedVersion.id, controller.signal).catch((reason) => {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
        setError(reason instanceof Error ? reason.message : t('卷册加载失败'));
      }
    });
    return () => controller.abort();
  }, [loadAllVolumes, selectedVersion, t]);

  useEffect(() => {
    if (!work || !singleEbookVolume) return;
    let disposed = false;
    const controller = new AbortController();
    setChapterLoading(true);
    setChapterError('');
    void fetchEbookChapterDetail(work.id, singleEbookVolume.id, chapterPage, CHAPTER_DETAIL_PAGE_SIZE, controller.signal)
      .then((detail) => {
        if (!disposed) setChapterDetailState({ volumeId: singleEbookVolume.id, detail });
      })
      .catch((reason) => {
        if (!disposed) setChapterError(reason instanceof Error ? reason.message : t('章节加载失败'));
      })
      .finally(() => {
        if (!disposed) setChapterLoading(false);
      });
    return () => { disposed = true; controller.abort(); };
  }, [chapterPage, singleEbookVolume, t, work]);

  const updateReadingStatus = async (status: string) => {
    if (!work || !selectedVolume || (status !== 'UNREAD' && status !== 'FINISHED')) return;
    setReadingStatusBusy(true);
    try {
      await updateVolumeReadingStatus(selectedVolume.id, status);
      const nextWork = await fetchWork(bookId);
      setWork(nextWork);
      const nextVolume = selectedVolumeForWork(nextWork, nextWork.continueVolumeId);
      router.replace(workDetailHref(nextWork.id, nextVolume?.id, returnHref));
      feedback.success(t(status === 'FINISHED' ? '已标记为已读' : '已标记为未读'));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('阅读状态更新失败'));
    } finally {
      setReadingStatusBusy(false);
    }
  };

  const refreshAfterMetadataApply = async () => {
    try {
      setWork(await fetchWork(bookId));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('读取作品失败'));
    }
  };

  const runWorkAction = async (key: string, action: () => Promise<void>, success: string, refresh = true) => {
    setWorkActionBusy(key);
    try {
      await action();
      if (refresh) setWork(await fetchWork(bookId));
      feedback.success(t(success));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setWorkActionBusy(null);
    }
  };

  const uploadCover = async (file: File | null) => {
    if (!work || !file) return;
    await runWorkAction('upload-cover', async () => {
      await uploadWorkCover(work.id, file);
      setCoverRevision(Date.now());
    }, '自定义封面已保存');
  };

  const regenerateCover = async () => {
    if (!work) return;
    await runWorkAction('regenerate-cover', async () => {
      await regenerateWorkCover(work.id);
      setCoverRevision(Date.now());
    }, '封面已重新生成');
  };

  const invokeBookAction = (action: BookActionId) => {
    setTopActionsOpen(false);
    if (action === 'edit') {
      setEditingMetadata(true);
      window.requestAnimationFrame(() => document.getElementById('work-metadata-editor')?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    } else if (action === 'metadata') setMetadataLookupOpen(true);
    else if (action === 'upload-cover') coverInputRef.current?.click();
    else if (action === 'regenerate-cover') void regenerateCover();
    else if (action === 'download') void downloadCurrentVersion();
    else if (action === 'kindle') void openKindleSend();
  };

  const openKindleSend = async () => {
    if (!work) return;
    setWorkActionBusy('kindle');
    try {
      const loadedVersions = await Promise.all(work.versions.map(async (version) => ({
        ...version,
        volumes: version.volumes.length >= version.volumeCount
          ? version.volumes
          : await fetchAllVersionVolumes(work.id, version.id)
      })));
      setWork({ ...work, versions: loadedVersions });
      setKindleSendOpen(true);
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('卷册加载失败'));
    } finally {
      setWorkActionBusy(null);
    }
  };

  const downloadCurrentVersion = async () => {
    if (!work || !selectedVersion) return;
    setWorkActionBusy('download');
    try {
      const nextVolumes = selectedVersion.volumes.length >= selectedVersion.volumeCount
        ? selectedVersion.volumes
        : await fetchAllVersionVolumes(work.id, selectedVersion.id);
      const volumeIds = nextVolumes.filter((volume) => volume.readable).map((volume) => volume.id);
      if (volumeIds.length === 1 && volumeIds[0]) {
        window.location.href = volumeFileDownloadUrl(volumeIds[0]);
        return;
      }
      if (volumeIds.length === 0) return;
      const archive = await downloadVolumeArchive(work.id, volumeIds);
      const href = URL.createObjectURL(archive.blob);
      const anchor = document.createElement('a');
      anchor.href = href;
      anchor.download = archive.filename;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(href), 0);
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('下载失败'));
    } finally {
      setWorkActionBusy(null);
    }
  };

  const refreshWallVolumes = async () => {
    setWork(await fetchWork(bookId));
  };

  const invokeVolumeAction = async (action: VolumeActionId) => {
    if (!work || selectedWallVolumes.length === 0 || !canManage) return;
    const volumeIds = selectedWallVolumes.map((volume) => volume.id);
    setVolumeMenuPosition(null);
    if (action === 'download') {
      if (selectedWallVolumes.length === 1) {
        const volume = selectedWallVolumes[0];
        if (volume?.readable) window.location.href = volumeFileDownloadUrl(volume.id);
        return;
      }
      setVolumeActionBusy(action);
      try {
        const archive = await downloadVolumeArchive(work.id, volumeIds);
        const href = URL.createObjectURL(archive.blob);
        const anchor = document.createElement('a');
        anchor.href = href;
        anchor.download = archive.filename;
        anchor.click();
        window.setTimeout(() => URL.revokeObjectURL(href), 0);
      } catch (reason) {
        feedback.error(reason instanceof Error ? reason.message : t('下载失败'));
      } finally {
        setVolumeActionBusy(null);
      }
      return;
    }
    if (action === 'edit') {
      if (selectedWallVolume) setEditingWallVolumeId(selectedWallVolume.id);
      return;
    }
    if (action === 'set-media-kind') return;
    setVolumeActionBusy(action);
    try {
      const targetMediaKind = action === 'set-ebook' ? 'EBOOK' : action === 'set-comic' ? 'COMIC' : action === 'set-audiobook' ? 'AUDIOBOOK' : null;
      if (!targetMediaKind) return;
      await runVolumeBatchAction(work.id, { action: 'SET_MEDIA_KIND', volumeIds, targetMediaKind });
      wallSelection.clear();
      await refreshWallVolumes();
      feedback.success(t('已更新 {value0} 个卷册的媒体类型', { value0: selectedWallVolumes.length }));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setVolumeActionBusy(null);
    }
  };

  if (loading && !work) return <div className="flex min-h-[60vh] items-center justify-center"><LoaderCircle className="animate-spin text-[#ff4f2a]" /></div>;
  if (!work) return <div className="mx-auto max-w-lg p-8 text-center"><p className="text-stone-600">{error || t('作品不存在')}</p><Button className="mt-4" onClick={() => router.push(returnHref)}>返回书库</Button></div>;

  return (
    <div className="w-full">
      <button type="button" onClick={() => router.push(returnHref)} className="mb-6 inline-flex items-center gap-2 text-sm text-stone-600 hover:text-stone-950"><ArrowLeft size={17} /><I18nText>返回全部图书</I18nText></button>
      <section className="rounded-[22px] border border-[#f1ddd3] bg-[#fffaf7] p-5 sm:p-6">
        <div className="grid gap-6 lg:grid-cols-[190px_minmax(0,1fr)] xl:grid-cols-[190px_minmax(0,1fr)_230px]">
          <Cover book={{ id: work.id, title: work.title, author: work.author, coverUrl: coverRevision > 0 && work.coverUrl ? `${work.coverUrl}${work.coverUrl.includes('?') ? '&' : '?'}v=${coverRevision}` : work.coverUrl, gradient: work.gradient, coverStatus: work.coverStatus }} className="mx-auto aspect-[2/3] w-36 rounded-xl shadow-md sm:w-[190px] lg:mx-0" size="large" priority />
          <div className="flex min-w-0 flex-col py-1 lg:h-[285px]">
            <div className="flex flex-wrap items-center gap-2">{work.completed ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"><CheckCircle2 size={14} /><I18nText>已完成</I18nText></span> : null}</div>
            <h1 data-i18n-skip className="mt-2 line-clamp-2 text-3xl font-semibold leading-[1.15] tracking-tight text-stone-950 sm:text-[34px]" title={work.title}>{work.title}</h1>
            <p data-i18n-skip className="mt-3 text-base text-stone-600">{work.author}</p>
            {work.description ? <p data-i18n-skip className="mt-5 line-clamp-3 max-w-3xl whitespace-pre-line text-sm leading-7 text-stone-600" title={work.description}>{work.description}</p> : <p className="mt-5 text-sm text-stone-400"><I18nText>暂无简介</I18nText></p>}
            {selectedVolume && activeCopy ? <div className="mt-7 max-w-3xl lg:mt-auto">
              <div className="flex items-center gap-4">
                <span className="shrink-0 text-sm font-medium text-stone-700">{t(activeCopy.progress)}</span>
                <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-stone-200">
                  <div className="h-full rounded-full bg-[#ff4f26] transition-[width]" style={{ width: `${Math.max(0, Math.min(100, activeProgress))}%` }} />
                </div>
                <span className="w-14 text-right text-sm font-medium tabular-nums text-stone-700">{Math.round(activeProgress)}%</span>
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                <span className="font-medium text-stone-700">{t(activeCopy.position)}</span>
                <span data-i18n-skip className="text-stone-800">{currentPositionLabel(selectedVolume, chapterDetail, t)}</span>
              </div>
            </div> : null}
            {error ? <p className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
          </div>

          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end lg:col-start-2 xl:col-start-3 xl:flex-col xl:justify-end">
            {selectedVolume && activeCopy ? <Button
              disabled={!activeReaderHref}
              icon={selectedVolume.readerType === 'audio' ? Headphones : selectedVolume.readerType === 'comic' ? Images : BookOpen}
              onClick={() => activeReaderHref && router.push(activeReaderHref)}
              className="!h-12 !min-h-12 w-full !rounded-xl !bg-[#ff4f26] !px-8 !text-base !text-white hover:!bg-[#e84420] sm:flex-1 xl:!flex-none xl:w-full"
            >
              {t(activeProgress > 0 ? activeCopy.resume : activeCopy.start)}
            </Button> : null}
            <div className="flex w-full gap-2 xl:justify-end">
              {selectedVolume && activeCopy ? <Select
                value={readingStatus}
                options={[
                  { value: 'READING', label: selectedVolume.readerType === 'audio' ? '在听' : selectedVolume.readerType === 'comic' ? '在看' : '在读', disabled: readingStatus !== 'READING' },
                  { value: 'UNREAD', label: selectedVolume.readerType === 'audio' ? '未听' : selectedVolume.readerType === 'comic' ? '未看' : '未读' },
                  { value: 'FINISHED', label: selectedVolume.readerType === 'audio' ? '已听完' : selectedVolume.readerType === 'comic' ? '已看完' : '已读' }
                ]}
                onChange={(status) => void updateReadingStatus(status)}
                ariaLabel={t(activeCopy.status)}
                align="right"
                disabled={readingStatusBusy}
                className="min-w-0 flex-1 xl:min-w-[150px]"
                triggerClassName="!rounded-xl !border-[#ead8cf] !bg-white/80 !shadow-none hover:!border-orange-200"
                menuClassName="!rounded-xl !border-[#ead8cf]"
              /> : null}
              {workActions.length ? <div ref={topActionsRef} className="relative ml-auto">
                <button type="button" onClick={() => setTopActionsOpen((open) => !open)} className="flex h-11 w-12 items-center justify-center rounded-xl border border-[#ead8cf] bg-white/80 text-stone-600 transition hover:border-orange-200 hover:bg-white hover:text-stone-950" aria-label={t('更多图书操作')} aria-haspopup="menu" aria-expanded={topActionsOpen}>
                  <Ellipsis size={20} />
                </button>
              {topActionsOpen ? <div role="menu" className="absolute right-0 top-full z-40 mt-2 w-60 rounded-[18px] border border-stone-200 bg-white p-2 shadow-xl shadow-stone-900/10">
                  {workActions.map((action) => {
                    const item = BOOK_ACTION_DETAILS[action];
                    const Icon = item.icon;
                    return <div key={action}>
                    <button type="button" role="menuitem" disabled={workActionBusy !== null} onClick={() => invokeBookAction(action)} className="flex min-h-10 w-full items-center gap-3 rounded-xl px-3 text-left text-sm text-stone-700 transition hover:bg-stone-50 hover:text-stone-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-200 disabled:cursor-not-allowed disabled:opacity-50">
                      <Icon size={18} /><span>{t(item.label)}</span>
                      </button>
                    </div>;
                  })}
                </div> : null}
              </div> : null}
            </div>
          </div>
        </div>
      </section>

      <input ref={coverInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(event) => { void uploadCover(event.target.files?.[0] ?? null); event.currentTarget.value = ''; }} />

      <WorkMetadataEditor work={work} open={editingMetadata} onClose={() => setEditingMetadata(false)} onSaved={(nextWork) => { setWork(nextWork); setEditingMetadata(false); }} />

      <section className="mt-6 border-t border-stone-200 pt-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-stone-950"><I18nText>版本与内容</I18nText></h2>
            <p className="mt-1 text-sm text-stone-500">{t('{value0} 个版本。目录决定卷册名称与顺序，管理模式只编辑元数据。', { value0: work.versions.length })}</p>
          </div>
          {canManage ? <Button variant={managementMode ? 'secondary' : 'primary'} icon={Settings2} onClick={() => setManagementMode((current) => !current)} className={cn('!rounded-xl', !managementMode && '!bg-[#ff4f26] !text-white hover:!bg-[#e84420]')}>
            {managementMode ? t('完成管理') : t('管理卷册信息')}
          </Button> : null}
        </div>
        {showVersionHeadings ? (
          <div className="mt-6 space-y-5">
            {work.versions.length ? work.versions.map((version) => (
              <StructureVersionCard
                key={version.id}
                work={work}
                version={version}
                showHeading
                managementMode={managementMode}
                canManage={canManage}
                onLoadAll={async () => { await loadAllVolumes(version.id); }}
                onRefresh={async () => {
                  try {
                    setWork(await fetchWork(bookId));
                  } catch (reason) {
                    feedback.error(reason instanceof Error ? reason.message : t('刷新失败'));
                  }
                }}
              />
            )) : <div className="rounded-2xl border border-dashed border-stone-300 p-10 text-center text-sm text-stone-500"><I18nText>还没有可见卷册</I18nText></div>}
          </div>
        ) : singleEbookVolume ? (
          <div className="mt-6">
            <SingleVolumeChapterList
              volume={singleEbookVolume}
              detail={chapterDetail}
              loading={chapterLoading}
              error={chapterError}
              requestedPage={chapterPage}
              onPageChange={(page) => setChapterPagination({ volumeId: singleEbookVolume.id, page })}
            />
          </div>
        ) : (
        <section
          className="mt-6"
          data-volume-wall-selection-surface="true"
          onMouseDown={(event) => {
            if (event.button !== 0 || !(event.target instanceof Element) || event.target.closest('[data-volume-wall-card="true"]')) return;
            setVolumeMenuPosition(null);
            setVolumeMenuAnchor(null);
            wallSelection.clear();
          }}
        >
          {allVolumes.length ? <>
            <div>
              <h2 className="text-lg font-semibold text-stone-950"><I18nText>卷册</I18nText></h2>
              <p className="mt-1 text-sm text-stone-500">{t('{value0} 个卷册', { value0: allVolumes.length })}</p>
            </div>
            <div className="mt-5 grid grid-cols-[repeat(auto-fill,minmax(130px,160px))] gap-5">{allVolumes.map((volume, index) => <VolumeWallCard
              key={volume.id}
              work={work}
              volume={volume}
              position={index}
              canManage={canManage}
              selected={wallSelection.selectedIds.has(volume.id)}
              onBeginSelection={(event) => {
                setVolumeMenuPosition(null);
                wallSelection.beginCardSelection(event, volume.id);
              }}
              onEnterSelection={() => wallSelection.enterCard(volume.id)}
              onOpenContextMenu={(position, anchor) => {
                wallSelection.selectForContextMenu(volume.id);
                setVolumeMenuAnchor(anchor);
                setVolumeMenuPosition(position);
              }}
            />)}</div>
          </> : <div className="rounded-2xl border border-dashed border-stone-300 p-10 text-center text-sm text-stone-500"><I18nText>还没有可见卷册</I18nText></div>}
        </section>
        )}
      </section>

      {selectedWallVolumes.length > 0 && canManage ? <ContextActionMenu
        position={volumeMenuPosition}
        ariaLabel={t('管理卷册')}
        title={selectedWallVolumes.length === 1 ? selectedWallVolumes[0]?.title ?? '' : t('批量管理卷册')}
        badge={t('已选 {value0} 卷', { value0: selectedWallVolumes.length })}
        items={wallVolumeActions.filter(({ action }) => action !== 'set-ebook' && action !== 'set-comic' && action !== 'set-audiobook').map(({ action, disabled }) => {
          const details = VOLUME_ACTION_DETAILS[action];
          return {
            action,
            label: t(details.label),
            description: t(details.description),
            icon: details.icon,
            disabled: disabled || volumeActionBusy !== null,
            submenu: action === 'set-media-kind' ? wallVolumeActions.filter((candidate) => candidate.action === 'set-ebook' || candidate.action === 'set-comic' || candidate.action === 'set-audiobook').map((candidate) => {
              const submenuDetails = VOLUME_ACTION_DETAILS[candidate.action];
              return {
                action: candidate.action,
                label: t(submenuDetails.label),
                description: t(submenuDetails.description),
                icon: submenuDetails.icon,
                disabled: candidate.disabled || volumeActionBusy !== null
              };
            }) : undefined
          };
        })}
        footer={t('Ctrl/Command + 点击可多选；按住左键扫过可快速选择；双击打开。')}
        returnFocusTo={volumeMenuAnchor}
        onClose={() => setVolumeMenuPosition(null)}
        onSelect={(action) => { void invokeVolumeAction(action); }}
      /> : null}

      <VolumeContextEditDialog
        work={work}
        volume={allVolumes.find((volume) => volume.id === editingWallVolumeId) ?? null}
        onClose={() => setEditingWallVolumeId(null)}
        onSaved={refreshWallVolumes}
      />

      <MetadataLookupModal book={work} currentVersionId={selectedVolume?.versionId ?? null} open={metadataLookupOpen} onClose={() => setMetadataLookupOpen(false)} onApplied={refreshAfterMetadataApply} />
      <KindleSendModal book={work} open={kindleSendOpen} preferredVolumeId={selectedVolume?.id ?? null} onClose={() => setKindleSendOpen(false)} />
    </div>
  );
}
