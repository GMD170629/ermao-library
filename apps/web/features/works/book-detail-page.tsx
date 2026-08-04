'use client';

import { ArrowLeft, BookOpen, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Database, Download, Edit3, Ellipsis, Headphones, ImageUp, Images, LoaderCircle, MoveRight, RefreshCw, RotateCcw, Scissors, Send, Settings2, Trash2, X, type LucideIcon } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useId, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { Cover } from '../../components/book/cover';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { ContextActionMenu, type ContextMenuPosition } from '../../components/ui/context-action-menu';
import { useToast } from '../../components/ui/feedback';
import { useAppSession } from '../../components/layout/app-session-context';
import { Select } from '../../components/ui/select';
import type { MediaKind, MediaVersionResource, ReaderType, VolumeResource, WorkDetailTabKey, WorkView } from '../../types/work';
import { I18nText } from '@/i18n/provider';
import { useI18n } from '@/i18n/provider';
import { deleteVolume, deleteWorkRecord, downloadVolumeArchive, fetchAllMediaVersionVolumes, fetchEbookChapterDetail, fetchWork, reclassifyVolume, regenerateWorkCover, runVolumeAction, runVolumeBatchAction, searchWorkTransferTargets, undoLibraryOperation, updateVolume, updateWorkReadingStatus, uploadWorkCover, type WorkTransferTarget } from './api/client';
import { useVolumeWallSelection } from './application/use-volume-wall-selection';
import { detailTabsForBook, displayVolumeNumber, formatDuration, isWorkDetailTabKey, resolvedDetailTab, selectedVolumeForDetailTab, volumesForDetailTab, workDetailTabHref } from './work-detail-tabs';
import { smallVolumeCoverUrl } from './volume-cover-url';
import { KindleSendModal } from './kindle-send-modal';
import { MetadataLookupModal } from './metadata-lookup-modal';
import { bookActionIds, type BookActionId } from './model/book-action-menu';
import { CHAPTER_DETAIL_PAGE_SIZE, singleVolumeEbook, type EbookChapterDetail } from './model/chapter-detail';
import { structureFileLabel } from './model/structure-file-label';
import { structureVolumeList } from './model/structure-volume-list';
import { volumeActionAvailability, type VolumeActionId } from './model/volume-action-menu';
import { SingleVolumeChapterList } from './ui/single-volume-chapter-list';
import { WorkMetadataEditor } from './ui/work-metadata-editor';

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

const BOOK_ACTION_DETAILS: Record<BookActionId, { label: string; icon: LucideIcon }> = {
  edit: { label: '编辑信息', icon: Edit3 },
  metadata: { label: '元数据识别', icon: Database },
  'upload-cover': { label: '上传自定义封面', icon: ImageUp },
  'regenerate-cover': { label: '重新生成封面', icon: RefreshCw },
  download: { label: '下载当前版本', icon: Download },
  kindle: { label: '发送到 Kindle', icon: Send },
  delete: { label: '删除记录', icon: Trash2 }
};

const VOLUME_ACTION_DETAILS: Record<VolumeActionId, { label: string; description: string; icon: LucideIcon }> = {
  download: { label: '下载', description: '下载所选卷册的源文件', icon: Download },
  edit: { label: '编辑', description: '修改名称、排序和卷册信息', icon: Edit3 },
  'set-media-kind': { label: '设置媒体类型', description: '将卷册归类为其他媒体类型', icon: Settings2 },
  'set-ebook': { label: '设置为电子书', description: '使用电子书方式管理和阅读', icon: BookOpen },
  'set-comic': { label: '设置为漫画', description: '使用漫画方式管理和阅读', icon: Images },
  'set-audiobook': { label: '设置为有声书', description: '使用有声书方式管理和收听', icon: Headphones },
  split: { label: '拆分为作品', description: '将卷册拆分为独立图书', icon: Scissors },
  transfer: { label: '转移', description: '移动到另一图书的对应版本', icon: MoveRight },
  delete: { label: '删除', description: '删除卷册及其阅读数据', icon: Trash2 }
};

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

function currentPositionLabel(volume: VolumeResource, translate: (source: string, values?: Record<string, string | number>) => string): string {
  if (volume.readerType === 'audio' && volume.durationMs) return formatDuration(volume.durationMs * volume.progress / 100);
  if ((volume.readerType === 'comic' || volume.readerType === 'pdf') && volume.pageCount) return translate('第 {value0} 页', { value0: Math.max(1, Math.ceil(volume.pageCount * volume.progress / 100)) });
  if (volume.chapterCount) return translate('第 {value0} 章', { value0: Math.max(1, Math.ceil(volume.chapterCount * volume.progress / 100)) });
  return volume.title;
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
      aria-label={t('第 {value0} 卷', { value0: number })}
      aria-pressed={canManage ? selected : undefined}
      className={cn('group min-w-0 text-left', !volume.readable && !canManage && 'cursor-not-allowed opacity-50')}
    >
      <div className={cn('relative overflow-hidden rounded-xl bg-stone-100 shadow-sm transition group-hover:-translate-y-0.5 group-hover:shadow-md group-focus-visible:outline group-focus-visible:outline-2 group-focus-visible:outline-offset-2 group-focus-visible:outline-[#ff4f2a]', selected && 'ring-2 ring-[#ff4f2a] ring-offset-2')}>
        <Cover book={{ id: volume.id, title: volume.title, author: work.author, coverUrl: smallVolumeCoverUrl(volume.id, volume.coverUrl), gradient: work.gradient, coverStatus: '' }} className="aspect-[2/3] w-full rounded-none" size="small" />
        <span className="absolute left-2 top-2 rounded-full bg-white/90 px-2 py-0.5 text-[11px] tabular-nums text-stone-600 shadow-sm">{String(number).padStart(2, '0')}</span>
        {selected ? <span className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-full bg-[#ff4f2a] text-white shadow-sm" aria-hidden="true"><Check size={14} strokeWidth={3} /></span> : null}
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
        title: form.title.trim(),
        volumeIndex: form.volumeIndex.trim() ? Number(form.volumeIndex) : null,
        sortOrder: Number(form.sortOrder),
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
        <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>卷册名称</I18nText><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>卷号（可选且可重复）</I18nText><input inputMode="decimal" value={form.volumeIndex} onChange={(event) => setForm({ ...form, volumeIndex: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        <label className="text-sm text-stone-600"><I18nText>排序</I18nText><input inputMode="numeric" value={form.sortOrder} onChange={(event) => setForm({ ...form, sortOrder: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
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

function VolumeContextTransferDialog({ work, volumes, onClose, onTransferred }: { work: WorkView; volumes: VolumeResource[]; onClose: () => void; onTransferred: (deletedWork: boolean) => Promise<void> }) {
  const feedback = useToast();
  const { t } = useI18n();
  const [targetSearch, setTargetSearch] = useState('');
  const [targets, setTargets] = useState<WorkTransferTarget[]>([]);
  const [selectedTargetId, setSelectedTargetId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [transferring, setTransferring] = useState(false);

  useEffect(() => {
    if (!volumes.length) return;
    setTargetSearch('');
    setTargets([]);
    setSelectedTargetId('');
    setError('');
  }, [volumes]);

  useEffect(() => {
    if (!volumes.length) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setLoading(true);
      setError('');
      void searchWorkTransferTargets(targetSearch, work.id, controller.signal).then(setTargets).catch((reason) => {
        if (!(reason instanceof DOMException && reason.name === 'AbortError')) setError(reason instanceof Error ? reason.message : t('目标图书加载失败'));
      }).finally(() => setLoading(false));
    }, 250);
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [targetSearch, t, volumes, work.id]);

  if (!volumes.length) return null;
  const transfer = async () => {
    if (!selectedTargetId) return;
    setTransferring(true);
    try {
      const result = await runVolumeBatchAction(work.id, { action: 'TRANSFER', volumeIds: volumes.map((volume) => volume.id), targetWorkId: selectedTargetId });
      await onTransferred(result.deletedWork);
      feedback.success(t('已转移 {value0} 个卷册', { value0: volumes.length }));
      onClose();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('卷册转移失败'));
    } finally {
      setTransferring(false);
    }
  };
  return <div className="fixed inset-0 z-[120] flex items-end justify-center bg-stone-950/40 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('转移卷册')}>
    <div className="w-full max-w-xl rounded-t-[26px] border border-stone-200 bg-white p-5 shadow-2xl md:rounded-[26px]">
      <div className="flex items-start justify-between gap-4"><div><h2 className="text-lg font-semibold text-stone-950"><I18nText>转移卷册</I18nText></h2><p className="mt-2 text-sm text-stone-600">{volumes.length === 1 ? <span data-i18n-skip>{volumes[0]?.title}</span> : t('将转移 {value0} 个卷册', { value0: volumes.length })}</p></div><button type="button" onClick={onClose} className="flex h-10 w-10 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100" aria-label={t('关闭')}><X size={18} /></button></div>
      <label className="mt-5 block text-sm font-medium text-stone-700"><I18nText>目标图书</I18nText><input value={targetSearch} onChange={(event) => setTargetSearch(event.target.value)} placeholder={t('搜索标题或作者')} className="mt-2 h-11 w-full rounded-xl border border-stone-200 px-3 text-sm outline-none focus:border-orange-300" /></label>
      <div className="mt-3 max-h-72 space-y-2 overflow-auto pr-1">
        {targets.map((target) => <button key={target.id} type="button" onClick={() => setSelectedTargetId(target.id)} className={cn('w-full rounded-xl border p-3 text-left transition', selectedTargetId === target.id ? 'border-orange-200 bg-[#fff4ef]' : 'border-stone-100 bg-stone-50 hover:bg-stone-100')}><span data-i18n-skip className="block truncate text-sm font-medium text-stone-950">{target.title}</span><span data-i18n-skip className="mt-1 block truncate text-xs text-stone-500">{target.author}</span></button>)}
        {loading ? <div className="rounded-xl bg-stone-50 p-3 text-sm text-stone-500"><I18nText>正在搜索…</I18nText></div> : null}
        {!loading && error ? <div className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        {!loading && !error && targets.length === 0 ? <div className="rounded-xl bg-stone-50 p-3 text-sm text-stone-500"><I18nText>没有找到可转移的目标图书</I18nText></div> : null}
      </div>
      <p className="mt-4 text-xs leading-5 text-stone-500"><I18nText>卷册及其阅读数据将移动到目标图书，并按媒介类型归入对应版本。</I18nText></p>
      <div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={onClose}><I18nText>取消</I18nText></Button><Button icon={MoveRight} loading={transferring} loadingText={t('转移中')} disabled={!selectedTargetId} onClick={() => void transfer()}><I18nText>确认转移</I18nText></Button></div>
    </div>
  </div>;
}

function visibleVersionVolumes(mediaVersion: MediaVersionResource): VolumeResource[] {
  return mediaVersion.volumes
    .filter((volume) => !volume.hidden)
    .sort((left, right) => left.sortOrder - right.sortOrder || left.id.localeCompare(right.id));
}

function mediaKindLabel(mediaKind: MediaKind): string {
  if (mediaKind === 'COMIC') return '漫画';
  if (mediaKind === 'AUDIOBOOK') return '有声书';
  return '电子书';
}

function classificationLabel(volume: VolumeResource): string {
  if (volume.classification.source === 'MONITOR_FOLDER') return '来自监控文件夹规则';
  if (volume.classification.source === 'USER') return '手动设置';
  if (volume.classification.reason === 'COMIC_SUBJECT') return '自动识别 · 包含漫画主题';
  if (volume.classification.source === 'AUTO') return '自动识别 · 默认按电子书处理';
  if (volume.classification.source === 'INHERITED') return '继承源卷册分类';
  return '旧数据分类';
}

function volumeUnitLabel(volume: VolumeResource, translate: (source: string, values?: Record<string, string | number>) => string): string {
  if (volume.pageCount) return translate('{value0} 页', { value0: volume.pageCount });
  if (volume.chapterCount) return translate('{value0} 章', { value0: volume.chapterCount });
  if (volume.trackCount) return translate('{value0} 音轨', { value0: volume.trackCount });
  return '';
}

function StructureVersionCard({
  work,
  mediaVersion,
  managementMode,
  canManage,
  onLoadAll,
  onRefresh
}: {
  work: WorkView;
  mediaVersion: MediaVersionResource;
  managementMode: boolean;
  canManage: boolean;
  onLoadAll: () => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const router = useRouter();
  const feedback = useToast();
  const { formatNumber, t } = useI18n();
  const [managedVolumeId, setManagedVolumeId] = useState<string | null>(null);
  const [movingVolumeId, setMovingVolumeId] = useState<string | null>(null);
  const [targetSearch, setTargetSearch] = useState('');
  const [transferTargets, setTransferTargets] = useState<WorkTransferTarget[]>([]);
  const [selectedTargetWorkId, setSelectedTargetWorkId] = useState('');
  const [targetsLoading, setTargetsLoading] = useState(false);
  const [targetError, setTargetError] = useState('');
  const [transferring, setTransferring] = useState(false);
  const [busyMoveId, setBusyMoveId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loadingAll, setLoadingAll] = useState(false);
  const volumeListId = useId();
  const volumes = visibleVersionVolumes(mediaVersion);
  const { visibleVolumes, canToggle } = structureVolumeList(volumes, expanded, mediaVersion.volumeCount);
  const firstReadableVolume = volumes.find((volume) => volume.readable) ?? null;
  const movingVolume = volumes.find((volume) => volume.id === movingVolumeId) ?? null;
  const totalSizeBytes = mediaVersion.sizeBytes;
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
      if (volumes.length < mediaVersion.volumeCount) await onLoadAll();
      setExpanded(true);
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('卷册加载失败'));
    } finally {
      setLoadingAll(false);
    }
  };

  const moveVolume = async (volume: VolumeResource, direction: 'up' | 'down') => {
    setBusyMoveId(volume.id);
    try {
      await runVolumeAction(work.id, volume.id, 'move', { direction });
      await onRefresh();
      feedback.success(t('卷册顺序已更新'));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('卷册顺序更新失败'));
    } finally {
      setBusyMoveId(null);
    }
  };

  useEffect(() => {
    if (!movingVolume) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setTargetsLoading(true);
      setTargetError('');
      void searchWorkTransferTargets(targetSearch, work.id, controller.signal)
        .then(setTransferTargets)
        .catch((reason) => {
          if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
            setTargetError(reason instanceof Error ? reason.message : t('目标图书加载失败'));
          }
        })
        .finally(() => setTargetsLoading(false));
    }, 250);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [movingVolume, targetSearch, t, work.id]);

  const openTransfer = (volume: VolumeResource) => {
    setMovingVolumeId(volume.id);
    setTargetSearch('');
    setTransferTargets([]);
    setSelectedTargetWorkId('');
    setTargetError('');
  };

  const transferVolume = async () => {
    if (!movingVolume || !selectedTargetWorkId) return;
    setTransferring(true);
    try {
      await runVolumeAction(work.id, movingVolume.id, 'move-to', { targetWorkId: selectedTargetWorkId });
      setMovingVolumeId(null);
      feedback.success(t('卷册已转移'));
      const totalVolumes = work.mediaVersions.reduce((total, version) => total + version.volumeCount, 0);
      if (totalVolumes <= 1) router.push('/library');
      else await onRefresh();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('卷册转移失败'));
    } finally {
      setTransferring(false);
    }
  };

  return (
    <article className="rounded-2xl border border-stone-200 bg-white">
      <div className="flex flex-wrap items-center gap-4 p-4 sm:p-5">
        <span className="inline-flex min-w-16 justify-center rounded-lg border border-orange-100 bg-orange-50 px-3 py-2 text-xs font-semibold text-amber-700">{t(mediaKindLabel(mediaVersion.mediaKind))}</span>
        <div className="min-w-[220px] flex-1">
          <div className="text-xs text-stone-500">
            {[sizeLabel, t('{value0} 个卷册', { value0: mediaVersion.volumeCount })].filter(Boolean).join(' · ')}
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
                {volume.files.map((file) => {
                  const label = structureFileLabel(volume.readerType, file.path);
                  return <span key={file.id} data-i18n-skip className="mt-0.5 block truncate text-xs text-stone-400" title={label}>{label}</span>;
                })}
              </div>
              <span className="text-xs text-stone-400">{volumeUnitLabel(volume, t)}</span>
              {managementMode ? <div className="flex items-center gap-1">
                <button type="button" disabled={busyMoveId !== null || index === 0} onClick={() => void moveVolume(volume, 'up')} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100 disabled:opacity-30" aria-label={t('上移 {value0}', { value0: volume.title })}><ChevronUp size={16} /></button>
                <button type="button" disabled={busyMoveId !== null || index === mediaVersion.volumeCount - 1} onClick={() => void moveVolume(volume, 'down')} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100 disabled:opacity-30" aria-label={t('下移 {value0}', { value0: volume.title })}><ChevronDown size={16} /></button>
                <button type="button" aria-expanded={managedVolumeId === volume.id} onClick={() => setManagedVolumeId((current) => current === volume.id ? null : volume.id)} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100" aria-label={t('编辑 {value0}', { value0: volume.title })}><Edit3 size={15} /></button>
                <button type="button" onClick={() => openTransfer(volume)} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100" aria-label={t('转移 {value0}', { value0: volume.title })}><MoveRight size={16} /></button>
              </div> : <button type="button" disabled={!volume.readable} onClick={() => router.push(readerHref(volume))} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-500 hover:bg-stone-100 disabled:opacity-30" aria-label={t('打开 {value0}', { value0: volume.title })}><ChevronRight size={16} /></button>}
            </div>
            {managementMode && managedVolumeId === volume.id ? <div className="pb-4 pt-2">
              <VolumeCard work={work} mediaKind={mediaVersion.mediaKind} volume={volume} canManage={canManage} onRefresh={onRefresh} />
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
          {loadingAll ? t('正在加载全部卷册…') : expanded ? t('收起卷册') : t('展开全部（共 {value0} 卷）', { value0: mediaVersion.volumeCount })}
        </button> : null}
      </div> : <div className="border-t border-stone-100 px-5 py-3 text-sm text-stone-400"><I18nText>该媒介还没有可见卷册</I18nText></div>}

      {movingVolume ? <div className="fixed inset-0 z-[110] flex items-end justify-center bg-stone-950/40 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('转移卷册')}>
        <div className="w-full max-w-xl rounded-t-[26px] border border-stone-200 bg-white p-5 shadow-2xl md:rounded-[26px]">
          <div className="flex items-start justify-between gap-4">
            <div><h2 className="text-lg font-semibold text-stone-950"><I18nText>转移卷册</I18nText></h2><p data-i18n-skip className="mt-2 text-sm text-stone-600">{movingVolume.title}</p></div>
            <button type="button" onClick={() => setMovingVolumeId(null)} className="flex h-10 w-10 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100" aria-label={t('关闭')}><X size={18} /></button>
          </div>
          <label className="mt-5 block text-sm font-medium text-stone-700"><I18nText>目标图书</I18nText>
            <input value={targetSearch} onChange={(event) => setTargetSearch(event.target.value)} placeholder={t('搜索标题或作者')} className="mt-2 h-11 w-full rounded-xl border border-stone-200 px-3 text-sm outline-none focus:border-orange-300" />
          </label>
          <div className="mt-3 max-h-72 space-y-2 overflow-auto pr-1">
            {transferTargets.map((target) => <button key={target.id} type="button" onClick={() => setSelectedTargetWorkId(target.id)} className={cn('w-full rounded-xl border p-3 text-left transition', selectedTargetWorkId === target.id ? 'border-orange-200 bg-[#fff4ef]' : 'border-stone-100 bg-stone-50 hover:bg-stone-100')}>
              <span data-i18n-skip className="block truncate text-sm font-medium text-stone-950">{target.title}</span>
              <span data-i18n-skip className="mt-1 block truncate text-xs text-stone-500">{target.author}</span>
            </button>)}
            {targetsLoading ? <div className="rounded-xl bg-stone-50 p-3 text-sm text-stone-500"><I18nText>正在搜索…</I18nText></div> : null}
            {!targetsLoading && targetError ? <div className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{targetError}</div> : null}
            {!targetsLoading && !targetError && transferTargets.length === 0 ? <div className="rounded-xl bg-stone-50 p-3 text-sm text-stone-500"><I18nText>没有找到可转移的目标图书</I18nText></div> : null}
          </div>
          <p className="mt-4 text-xs leading-5 text-stone-500"><I18nText>卷册及其阅读数据将移动到目标图书，并按媒介类型归入对应版本。</I18nText></p>
          <div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={() => setMovingVolumeId(null)}><I18nText>取消</I18nText></Button><Button icon={MoveRight} loading={transferring} loadingText={t('转移中')} disabled={!selectedTargetWorkId} onClick={() => void transferVolume()}><I18nText>确认转移</I18nText></Button></div>
        </div>
      </div> : null}
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
      title: form.title.trim(),
      volumeIndex: form.volumeIndex.trim() ? Number(form.volumeIndex) : null,
      sortOrder: Number(form.sortOrder),
      publisher: form.publisher.trim() || null,
      language: form.language.trim() || null,
      isbn: form.isbn.trim() || null,
      identifier: form.identifier.trim() || null,
      narrator: form.narrator.trim() || null
    }).then(async () => {
      if (targetMediaKind === mediaKind) return;
      const operationId = await reclassifyVolume(work.id, volume.id, targetMediaKind, applyToVersion ? 'MEDIA_VERSION' : 'VOLUME');
      setUndoOperationId(operationId);
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
          {volume.derivedFromVolumeId ? <span><I18nText>派生卷册</I18nText></span> : null}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2 border-t border-stone-100 pt-4">
          {undoOperationId ? <Button variant="secondary" icon={RotateCcw} loading={busy === 'undo-classification'} onClick={() => void run('undo-classification', async () => { await undoLibraryOperation(undoOperationId); setUndoOperationId(null); }, '已撤销内容分类调整')}>撤销分类调整</Button> : null}
          {canManage ? <><Button variant="secondary" icon={Download} onClick={() => { window.location.href = `/api/volumes/${encodeURIComponent(volume.id)}/file`; }}>
            下载
          </Button>
          <Button variant="ghost" icon={Edit3} onClick={() => setEditing(true)}>编辑卷册</Button>
          {volume.conversionAvailable ? <Button variant="ghost" icon={RefreshCw} loading={busy === 'convert'} onClick={() => void run('convert', () => runVolumeAction(work.id, volume.id, 'convert'), '已创建或刷新派生卷册')}>转换为 EPUB</Button> : null}
          <Button variant="ghost" icon={Scissors} loading={busy === 'split'} onClick={() => void run('split', () => runVolumeAction(work.id, volume.id, 'split', { title: `${work.title}（${volume.title}）`, author: work.author, copyShelves: true }), '卷册已拆分为新作品')}>拆分为作品</Button>
          <Button variant="danger" icon={Trash2} loading={busy === 'delete'} onClick={() => void remove()}>删除卷册</Button></> : null}
      </div>

      {editing ? (
        <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/45 md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('编辑卷册')}>
          <div className="w-full max-w-xl rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
            <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>编辑卷册</I18nText></h2><button type="button" onClick={() => setEditing(false)} aria-label={t('关闭')}><X size={20} /></button></div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>当前内容分类</I18nText><Select value={targetMediaKind} onChange={setTargetMediaKind} ariaLabel="当前内容分类" className="mt-1.5 w-full" options={[{ value: 'EBOOK', label: '电子书' }, { value: 'COMIC', label: '漫画' }, { value: 'AUDIOBOOK', label: '有声书' }]} /><span className="mt-1.5 block text-xs text-stone-500">{t(classificationLabel(volume))}</span>{volume.classification.suggestedMediaKind === 'COMIC' ? <button type="button" className="mt-2 rounded-lg bg-orange-50 px-2.5 py-1.5 text-xs font-medium text-orange-700" onClick={() => setTargetMediaKind('COMIC')}>{t('可能是漫画 · 改为漫画')}</button> : null}</label>
              <label className="flex items-center gap-2 text-sm text-stone-600 sm:col-span-2"><input type="checkbox" checked={applyToVersion} onChange={(event) => setApplyToVersion(event.target.checked)} />{t('同时应用到此版本全部 {value0} 个卷册', { value0: work.mediaVersions.find((version) => version.id === volume.mediaVersionId)?.volumeCount ?? 1 })}</label>
              <label className="text-sm text-stone-600 sm:col-span-2"><I18nText>卷册名称</I18nText><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>卷号（可选且可重复）</I18nText><input inputMode="decimal" value={form.volumeIndex} onChange={(event) => setForm({ ...form, volumeIndex: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
              <label className="text-sm text-stone-600"><I18nText>排序</I18nText><input inputMode="numeric" value={form.sortOrder} onChange={(event) => setForm({ ...form, sortOrder: event.target.value })} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
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
  const [transferringWallVolumes, setTransferringWallVolumes] = useState(false);
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

  const requestedTab = isWorkDetailTabKey(searchParams.get('detailTab')) ? searchParams.get('detailTab') as WorkDetailTabKey : null;
  const requestedVolumeId = searchParams.get('volumeId')?.trim() || null;
  const tab = work ? resolvedDetailTab(work, requestedTab) : 'STRUCTURE';
  const selectedVolume = work ? selectedVolumeForDetailTab(work, tab, requestedVolumeId) : null;
  const tabs = useMemo(() => work ? detailTabsForBook(work) : [], [work]);
  const volumes = useMemo(() => work ? volumesForDetailTab(work, tab) : [], [tab, work]);
  const singleEbookVolume = singleVolumeEbook(tab, volumes);
  const wallVolumeIds = useMemo(() => volumes.map((volume) => volume.id), [volumes]);
  const wallSelection = useVolumeWallSelection({
    enabled: canManage && tab !== 'STRUCTURE' && !singleEbookVolume,
    scopeKey: tab,
    volumeIds: wallVolumeIds
  });
  const chapterPage = singleEbookVolume && chapterPagination.volumeId === singleEbookVolume.id ? chapterPagination.page : 1;
  const chapterDetail = singleEbookVolume && chapterDetailState?.volumeId === singleEbookVolume.id ? chapterDetailState.detail : null;
  const structureMediaVersions = useMemo(() => work
    ? work.availableMediaKinds.flatMap((mediaKind) => work.mediaVersions.filter((mediaVersion) => mediaVersion.mediaKind === mediaKind))
    : [], [work]);
  const activeMediaKind = tab === 'STRUCTURE' ? null : tab;
  const activeProgress = selectedVolume?.progress ?? 0;
  const activeCopy = selectedVolume ? consumptionCopy(selectedVolume.readerType) : null;
  const activeReaderHref = selectedVolume?.readable ? readerHref(selectedVolume) : null;
  const readingStatus = activeProgress >= 100 ? 'FINISHED' : activeProgress > 0 ? 'READING' : 'UNREAD';
  const workActions = bookActionIds({
    canManage,
    hasDownload: Boolean(selectedVolume?.readable),
    kindleSendAvailable: selectedVolume?.kindleSendAvailable === true
  });
  const currentWorkId = work?.id;

  const loadAllVolumes = useCallback(async (mediaVersionId: string, signal?: AbortSignal) => {
    if (!currentWorkId) return [];
    const nextVolumes = await fetchAllMediaVersionVolumes(currentWorkId, mediaVersionId, signal);
    setWork((current) => current ? {
      ...current,
      mediaVersions: current.mediaVersions.map((mediaVersion) => mediaVersion.id === mediaVersionId
        ? { ...mediaVersion, volumes: nextVolumes, volumeCount: nextVolumes.length }
        : mediaVersion)
    } : current);
    return nextVolumes;
  }, [currentWorkId]);

  const selectedMediaVersion = activeMediaKind && work
    ? work.mediaVersions.find((mediaVersion) => mediaVersion.mediaKind === activeMediaKind) ?? null
    : null;
  const selectedWallVolumes = useMemo(() => volumes.filter((volume) => wallSelection.selectedIds.has(volume.id)), [volumes, wallSelection.selectedIds]);
  const selectedWallVolume = selectedWallVolumes.length === 1 ? selectedWallVolumes[0] ?? null : null;
  const wallVolumeActions = volumeActionAvailability({
    canManage,
    readable: selectedWallVolumes.length > 0 && selectedWallVolumes.every((volume) => volume.readable),
    mediaKind: activeMediaKind ?? 'EBOOK',
    selectionCount: selectedWallVolumes.length
  });

  useEffect(() => {
    setVolumeMenuPosition(null);
    setVolumeMenuAnchor(null);
  }, [tab]);

  useEffect(() => {
    if (!selectedMediaVersion || selectedMediaVersion.volumes.length >= selectedMediaVersion.volumeCount) return;
    const controller = new AbortController();
    void loadAllVolumes(selectedMediaVersion.id, controller.signal).catch((reason) => {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
        setError(reason instanceof Error ? reason.message : t('卷册加载失败'));
      }
    });
    return () => controller.abort();
  }, [loadAllVolumes, selectedMediaVersion, t]);

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
    if (!work || (status !== 'UNREAD' && status !== 'FINISHED')) return;
    setReadingStatusBusy(true);
    try {
      await updateWorkReadingStatus(work.id, status);
      setWork(await fetchWork(bookId));
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

  const removeWork = async () => {
    if (!work) return;
    const confirmed = await feedback.confirm({
      title: t('删除图书记录'),
      description: t('将删除这本图书的书库记录、阅读进度、书签和系统生成文件；源文件会保留。'),
      confirmLabel: t('删除记录'),
      tone: 'danger'
    });
    if (!confirmed) return;
    setWorkActionBusy('delete');
    try {
      await deleteWorkRecord(work.id);
      feedback.success(t('已删除图书记录'));
      router.push('/library');
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('删除失败'));
      setWorkActionBusy(null);
    }
  };

  const invokeBookAction = (action: BookActionId) => {
    setTopActionsOpen(false);
    if (action === 'edit') {
      setEditingMetadata(true);
      window.requestAnimationFrame(() => document.getElementById('work-metadata-editor')?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    } else if (action === 'metadata') setMetadataLookupOpen(true);
    else if (action === 'upload-cover') coverInputRef.current?.click();
    else if (action === 'regenerate-cover') void regenerateCover();
    else if (action === 'download' && selectedVolume) window.location.href = `/api/volumes/${encodeURIComponent(selectedVolume.id)}/file`;
    else if (action === 'kindle') void openKindleSend();
    else if (action === 'delete') void removeWork();
  };

  const openKindleSend = async () => {
    if (!work) return;
    setWorkActionBusy('kindle');
    try {
      const loadedVersions = await Promise.all(work.mediaVersions.map(async (mediaVersion) => ({
        ...mediaVersion,
        volumes: mediaVersion.volumes.length >= mediaVersion.volumeCount
          ? mediaVersion.volumes
          : await fetchAllMediaVersionVolumes(work.id, mediaVersion.id)
      })));
      setWork({ ...work, mediaVersions: loadedVersions });
      setKindleSendOpen(true);
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('卷册加载失败'));
    } finally {
      setWorkActionBusy(null);
    }
  };

  const selectTab = (next: WorkDetailTabKey) => {
    if (!work) return;
    const nextVolume = selectedVolumeForDetailTab(work, next, work.continueVolumeId);
    router.replace(workDetailTabHref(work.id, next, nextVolume?.id));
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
        if (volume?.readable) window.location.href = `/api/volumes/${encodeURIComponent(volume.id)}/file`;
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
    if (action === 'transfer') {
      setTransferringWallVolumes(true);
      return;
    }
    if (action === 'set-media-kind') return;
    if (action === 'delete') {
      const confirmed = await feedback.confirm({
        title: t('删除 {value0} 个卷册', { value0: selectedWallVolumes.length }),
        description: t('将删除所选卷册及其阅读进度、书签和任务。未选择的卷册会保留。'),
        confirmLabel: t('删除'),
        tone: 'danger'
      });
      if (!confirmed) return;
    }
    setVolumeActionBusy(action);
    try {
      const targetMediaKind = action === 'set-ebook' ? 'EBOOK' : action === 'set-comic' ? 'COMIC' : action === 'set-audiobook' ? 'AUDIOBOOK' : null;
      const result = targetMediaKind
        ? await runVolumeBatchAction(work.id, { action: 'SET_MEDIA_KIND', volumeIds, targetMediaKind })
        : action === 'split'
          ? await runVolumeBatchAction(work.id, { action: 'SPLIT', volumeIds })
          : await runVolumeBatchAction(work.id, { action: 'DELETE', volumeIds });
      wallSelection.clear();
      if (result.deletedWork) router.push('/library');
      else await refreshWallVolumes();
      feedback.success(t(
        targetMediaKind ? '已更新 {value0} 个卷册的媒体类型' : action === 'split' ? '已拆分 {value0} 个卷册为独立作品' : '已删除 {value0} 个卷册',
        { value0: selectedWallVolumes.length }
      ));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setVolumeActionBusy(null);
    }
  };

  if (loading && !work) return <div className="flex min-h-[60vh] items-center justify-center"><LoaderCircle className="animate-spin text-[#ff4f2a]" /></div>;
  if (!work) return <div className="mx-auto max-w-lg p-8 text-center"><p className="text-stone-600">{error || t('作品不存在')}</p><Button className="mt-4" onClick={() => router.push('/library')}>返回书库</Button></div>;

  return (
    <div className="w-full">
      <button type="button" onClick={() => router.push('/library')} className="mb-6 inline-flex items-center gap-2 text-sm text-stone-600 hover:text-stone-950"><ArrowLeft size={17} /><I18nText>返回全部图书</I18nText></button>
      <section className="rounded-[22px] border border-[#f1ddd3] bg-[#fffaf7] p-5 sm:p-6">
        <div className="grid gap-6 lg:grid-cols-[190px_minmax(0,1fr)] xl:grid-cols-[190px_minmax(0,1fr)_230px]">
          <Cover book={{ id: work.id, title: work.title, author: work.author, coverUrl: coverRevision > 0 && work.coverUrl ? `${work.coverUrl}${work.coverUrl.includes('?') ? '&' : '?'}v=${coverRevision}` : work.coverUrl, gradient: work.gradient, coverStatus: work.coverStatus }} className="mx-auto aspect-[2/3] w-36 rounded-xl shadow-md sm:w-[190px] lg:mx-0" size="large" priority />
          <div className="flex min-w-0 flex-col py-1 lg:h-[285px]">
            <div className="flex flex-wrap items-center gap-2">{work.completed ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"><CheckCircle2 size={14} /><I18nText>已完成</I18nText></span> : null}</div>
            <h1 data-i18n-skip className="mt-2 line-clamp-2 text-3xl font-semibold leading-[1.15] tracking-tight text-stone-950 sm:text-[34px]" title={work.title}>{work.title}</h1>
            <p data-i18n-skip className="mt-3 text-base text-stone-600">{work.author}</p>
            {work.description ? <p data-i18n-skip className="mt-5 line-clamp-3 max-w-3xl whitespace-pre-line text-sm leading-7 text-stone-600" title={work.description}>{work.description}</p> : <p className="mt-5 text-sm text-stone-400"><I18nText>暂无简介</I18nText></p>}
            {activeMediaKind && selectedVolume && activeCopy ? <div className="mt-7 max-w-3xl lg:mt-auto">
              <div className="flex items-center gap-4">
                <span className="shrink-0 text-sm font-medium text-stone-700">{t(activeCopy.progress)}</span>
                <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-stone-200">
                  <div className="h-full rounded-full bg-[#ff4f26] transition-[width]" style={{ width: `${Math.max(0, Math.min(100, activeProgress))}%` }} />
                </div>
                <span className="w-14 text-right text-sm font-medium tabular-nums text-stone-700">{Math.round(activeProgress)}%</span>
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                <span className="font-medium text-stone-700">{t(activeCopy.position)}</span>
                <span data-i18n-skip className="text-stone-800">{currentPositionLabel(selectedVolume, t)}</span>
              </div>
            </div> : null}
            {error ? <p className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
          </div>

          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end lg:col-start-2 xl:col-start-3 xl:flex-col xl:justify-end">
            {activeMediaKind && activeCopy ? <Button
              disabled={!activeReaderHref}
              icon={activeMediaKind === 'AUDIOBOOK' ? Headphones : activeMediaKind === 'COMIC' ? Images : BookOpen}
              onClick={() => activeReaderHref && router.push(activeReaderHref)}
              className="!h-12 !min-h-12 w-full !rounded-xl !bg-[#ff4f26] !px-8 !text-base !text-white hover:!bg-[#e84420] sm:flex-1 xl:!flex-none xl:w-full"
            >
              {t(activeProgress > 0 ? activeCopy.resume : activeCopy.start)}
            </Button> : null}
            <div className="flex w-full gap-2 xl:justify-end">
              {activeMediaKind && activeCopy ? <Select
                value={readingStatus}
                options={[
                  { value: 'READING', label: activeMediaKind === 'AUDIOBOOK' ? '在听' : '在看', disabled: readingStatus !== 'READING' },
                  { value: 'UNREAD', label: activeMediaKind === 'AUDIOBOOK' ? '未听' : '未读' },
                  { value: 'FINISHED', label: activeMediaKind === 'AUDIOBOOK' ? '已听完' : '已读' }
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
                    {action === 'delete' ? <div className="my-1.5 h-px bg-stone-100" /> : null}
                    <button type="button" role="menuitem" disabled={workActionBusy !== null} onClick={() => invokeBookAction(action)} className={cn('flex min-h-10 w-full items-center gap-3 rounded-xl px-3 text-left text-sm text-stone-700 transition hover:bg-stone-50 hover:text-stone-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-200 disabled:cursor-not-allowed disabled:opacity-50', action === 'delete' && 'hover:bg-red-50 hover:text-red-700')}>
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

      <nav className="mt-10 flex gap-2 overflow-x-auto border-b border-stone-200" aria-label={t('作品媒介')}>
        {tabs.map((item) => <button key={item.key} type="button" onClick={() => selectTab(item.key)} className={cn('min-h-11 shrink-0 border-b-2 px-4 text-sm font-medium', tab === item.key ? 'border-[#ff4f2a] text-[#d94322]' : 'border-transparent text-stone-500 hover:text-stone-900')}>{t(item.label)}</button>)}
      </nav>

      {tab === 'STRUCTURE' ? (
        <section className="mt-6 border-t border-stone-200 pt-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-stone-950"><I18nText>版本与内容</I18nText></h2>
              <p className="mt-1 text-sm text-stone-500">{t('{value0} 个版本 · 覆盖 {value1} 种媒介。管理模式下可调整卷册信息和位置。', { value0: structureMediaVersions.length, value1: work.availableMediaKinds.length })}</p>
            </div>
            {canManage ? <Button variant={managementMode ? 'secondary' : 'primary'} icon={Settings2} onClick={() => setManagementMode((current) => !current)} className={cn('!rounded-xl', !managementMode && '!bg-[#ff4f26] !text-white hover:!bg-[#e84420]')}>
              {managementMode ? t('完成管理') : t('管理内容结构')}
            </Button> : null}
          </div>
          <div className="mt-6 space-y-5">
            {structureMediaVersions.length ? structureMediaVersions.map((mediaVersion) => (
              <StructureVersionCard
                key={mediaVersion.id}
                work={work}
                mediaVersion={mediaVersion}
                managementMode={managementMode}
                canManage={canManage}
                onLoadAll={async () => { await loadAllVolumes(mediaVersion.id); }}
                onRefresh={async () => {
                  try {
                    setWork(await fetchWork(bookId));
                  } catch (reason) {
                    feedback.error(reason instanceof Error ? reason.message : t('刷新失败'));
                  }
                }}
              />
            )) : <div className="rounded-2xl border border-dashed border-stone-300 p-10 text-center text-sm text-stone-500"><I18nText>该媒介还没有可见卷册</I18nText></div>}
          </div>
        </section>
      ) : (
        singleEbookVolume ? <SingleVolumeChapterList
          volume={singleEbookVolume}
          detail={chapterDetail}
          loading={chapterLoading}
          error={chapterError}
          requestedPage={chapterPage}
          onPageChange={(page) => setChapterPagination({ volumeId: singleEbookVolume.id, page })}
        /> : <section
          className="mt-6"
          data-volume-wall-selection-surface="true"
          onMouseDown={(event) => {
            if (event.button !== 0 || !(event.target instanceof Element) || event.target.closest('[data-volume-wall-card="true"]')) return;
            setVolumeMenuPosition(null);
            setVolumeMenuAnchor(null);
            wallSelection.clear();
          }}
        >
          {volumes.length ? <>
            <div>
              <h2 className="text-lg font-semibold text-stone-950"><I18nText>卷册</I18nText></h2>
              <p className="mt-1 text-sm text-stone-500">{t('{value0} 个卷册', { value0: volumes.length })}</p>
            </div>
            <div className="mt-5 grid grid-cols-[repeat(auto-fill,minmax(130px,160px))] gap-5">{volumes.map((volume, index) => <VolumeWallCard
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
          </> : <div className="rounded-2xl border border-dashed border-stone-300 p-10 text-center text-sm text-stone-500"><I18nText>该媒介还没有可见卷册</I18nText></div>}
        </section>
      )}

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
            destructive: action === 'delete',
            separatorBefore: action === 'delete',
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
        volume={volumes.find((volume) => volume.id === editingWallVolumeId) ?? null}
        onClose={() => setEditingWallVolumeId(null)}
        onSaved={refreshWallVolumes}
      />
      <VolumeContextTransferDialog
        work={work}
        volumes={transferringWallVolumes ? selectedWallVolumes : []}
        onClose={() => setTransferringWallVolumes(false)}
        onTransferred={async (deletedWork) => {
          wallSelection.clear();
          if (deletedWork) router.push('/library');
          else await refreshWallVolumes();
        }}
      />

      <MetadataLookupModal book={work} currentMediaVersionId={selectedVolume?.mediaVersionId ?? null} open={metadataLookupOpen} onClose={() => setMetadataLookupOpen(false)} onApplied={refreshAfterMetadataApply} />
      <KindleSendModal book={work} open={kindleSendOpen} preferredVolumeId={selectedVolume?.id ?? null} onClose={() => setKindleSendOpen(false)} />
    </div>
  );
}
