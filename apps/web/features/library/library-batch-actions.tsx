'use client';

import {
  BookCheck,
  Braces,
  Check,
  Eye,
  Hash,
  ImagePlus,
  Images,
  LibraryBig,
  Minimize2,
  Replace,
  RotateCcw,
  Scissors,
  Tags,
  Trash2,
  UserRound,
  X
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useToast } from '../../components/ui/feedback';
import { Select, type SelectOption } from '../../components/ui/select';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import {
  canUseLibraryBatchAction,
  type LibraryBatchAction
} from './model/library-batch-action';

export type { LibraryBatchAction } from './model/library-batch-action';

type ContextPosition = { x: number; y: number };
type ShelfOption = { id: string; name: string; kind?: 'STATIC' | 'SMART' };
type BulkResponse = {
  ok: boolean;
  data?: {
    updated?: number;
    deleted?: number;
    deletedFiles?: number;
    deletedSourceFiles?: number;
    failedFileDeletes?: Array<{ path: string; message: string }>;
    changedValues?: number;
    skipped?: Array<{ workId: string; reason: string }>;
  };
  error?: { message?: string };
};
type FindReplacePreview = {
  changedWorks: number;
  changedValues: number;
  items: Array<{ workId: string; title: string; before: string | string[]; after: string | string[] }>;
};

const actions: Array<{ value: LibraryBatchAction; label: string; shortLabel: string; description: string; icon: LucideIcon }> = [
  { value: 'metadata', label: '批量更新元数据', shortLabel: '元数据', description: '作者、标签和系列', icon: Tags },
  { value: 'find_replace', label: '查找替换', shortLabel: '查找替换', description: '支持安全 Jinja 变量和递增序列', icon: Replace },
  { value: 'shelves', label: '加入或移除书架', shortLabel: '书架', description: '管理普通书架中的批量归属', icon: LibraryBig },
  { value: 'reading_status', label: '设置阅读状态', shortLabel: '阅读状态', description: '清空进度或统一设为 100%', icon: BookCheck },
  { value: 'covers', label: '批量设置封面', shortLabel: '封面', description: '裁剪、重新生成、压缩或替换', icon: Images },
  { value: 'delete', label: '批量删除图书', shortLabel: '删除', description: '删除书库记录，可选择同步删除源文件', icon: Trash2 }
];

const inputClass = 'h-11 w-full rounded-xl border border-black/[0.1] bg-white px-3.5 text-sm text-[#312D2A] outline-none transition placeholder:text-[#AAA49E] focus:border-[#E8A18D] focus:ring-4 focus:ring-[#FFE9E2]';
const textareaClass = 'min-h-24 w-full resize-y rounded-xl border border-black/[0.1] bg-white px-3.5 py-3 text-sm text-[#312D2A] outline-none transition placeholder:text-[#AAA49E] focus:border-[#E8A18D] focus:ring-4 focus:ring-[#FFE9E2]';

function splitValues(value: string) {
  return value.split(/[,，;；\n]/).map((item) => item.trim()).filter(Boolean);
}

function valueLabel(value: string | string[]) {
  return Array.isArray(value) ? value.join('、') : value || '（空）';
}

export function LibraryBatchContextMenu({
  position,
  selectedCount,
  canManageSystem,
  onClose,
  onSelect
}: {
  position: ContextPosition | null;
  selectedCount: number;
  canManageSystem: boolean;
  onClose: () => void;
  onSelect: (action: LibraryBatchAction) => void;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!position) return;
    function closeOnPointer(event: MouseEvent) {
      if (!menuRef.current?.contains(event.target as Node)) onClose();
    }
    function closeOnKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    function closeOnViewportChange() {
      onClose();
    }
    document.addEventListener('mousedown', closeOnPointer);
    document.addEventListener('keydown', closeOnKey);
    window.addEventListener('resize', closeOnViewportChange);
    window.addEventListener('scroll', closeOnViewportChange, true);
    return () => {
      document.removeEventListener('mousedown', closeOnPointer);
      document.removeEventListener('keydown', closeOnKey);
      window.removeEventListener('resize', closeOnViewportChange);
      window.removeEventListener('scroll', closeOnViewportChange, true);
    };
  }, [onClose, position]);

  if (!position || typeof document === 'undefined') return null;
  const width = 316;
  const height = 456;
  const left = Math.max(12, Math.min(position.x, window.innerWidth - width - 12));
  const top = Math.max(12, Math.min(position.y, window.innerHeight - height - 12));

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      aria-label={i18nAttribute("批量管理图书")}
      style={{ left, top, width }}
      className="fixed z-[130] overflow-hidden rounded-2xl border border-black/[0.1] bg-[#FFFEFC] p-2 shadow-[0_22px_70px_rgba(47,37,31,0.24)]"
    >
      <div className="flex items-center justify-between px-3 pb-2 pt-1.5">
        <span className="text-xs font-semibold text-[#625C56]"><I18nText>批量管理</I18nText></span>
        <span className="rounded-full bg-[#FFF0EA] px-2 py-1 text-[11px] font-medium text-[#D7462B]"><I18nText>已选 </I18nText>{selectedCount} <I18nText>本</I18nText></span>
      </div>
      <div className="space-y-0.5">
        {actions.filter((item) => canUseLibraryBatchAction(item.value, canManageSystem)).map((item) => {
          const Icon = item.icon;
          const destructive = item.value === 'delete';
          return (
            <button
              key={item.value}
              type="button"
              role="menuitem"
              onClick={() => onSelect(item.value)}
              className={cn(
                'group flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left outline-none transition',
                destructive
                  ? 'hover:bg-red-50 focus-visible:bg-red-50'
                  : 'hover:bg-[#FFF2ED] focus-visible:bg-[#FFF2ED]'
              )}
            >
              <span className={cn(
                'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition group-hover:bg-white',
                destructive ? 'bg-red-50 text-red-600' : 'bg-black/[0.035] text-[#746D67] group-hover:text-[#EF4D2F]'
              )}>
                <Icon size={16} />
              </span>
              <span className="min-w-0">
                <span className={cn('block text-sm font-medium', destructive ? 'text-red-700' : 'text-[#302C29]')}>{i18nAttribute(item.label)}</span>
                <span className="mt-0.5 block truncate text-[11px] text-[#8B847D]">{item.description}</span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-2 border-t border-black/[0.06] px-3 pt-2 text-[11px] leading-5 text-[#948D86]"><I18nText>拖动经过行可连续选择；按 Shift 点击可选择区间。</I18nText></div>
    </div>,
    document.body
  );
}

function FieldToggle({
  checked,
  onChange,
  icon: Icon,
  label,
  hint,
  children
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  icon: LucideIcon;
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  return (
    <div className={cn('rounded-2xl border p-4 transition', checked ? 'border-[#F1BAAA] bg-[#FFF9F6]' : 'border-black/[0.07] bg-white/60')}>
      <label className="flex cursor-pointer items-start gap-3">
        <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="mt-1 h-4 w-4 accent-[#EF4D2F]" />
        <span className="flex min-w-0 flex-1 items-start gap-2.5">
          <Icon size={17} className="mt-0.5 shrink-0 text-[#7C756E]" />
          <span>
            <span className="block text-sm font-semibold text-[#34302D]">{i18nAttribute(label)}</span>
            <span className="mt-0.5 block text-xs leading-5 text-[#8A837C]">{hint}</span>
          </span>
        </span>
      </label>
      {checked ? <div className="mt-3">{children}</div> : null}
    </div>
  );
}

export function LibraryBatchDialog({
  action,
  selectedIds,
  canManageSystem,
  onActionChange,
  onClose,
  onApplied
}: {
  action: LibraryBatchAction | null;
  selectedIds: string[];
  canManageSystem: boolean;
  onActionChange: (action: LibraryBatchAction) => void;
  onClose: () => void;
  onApplied: (message: string) => void;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const [authorEnabled, setAuthorEnabled] = useState(false);
  const [seriesEnabled, setSeriesEnabled] = useState(false);
  const [author, setAuthor] = useState('');
  const [seriesName, setSeriesName] = useState('');
  const [addTags, setAddTags] = useState('');
  const [removeTags, setRemoveTags] = useState('');
  const [findField, setFindField] = useState('title');
  const [findText, setFindText] = useState('');
  const [replacement, setReplacement] = useState('');
  const [regex, setRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [startNumber, setStartNumber] = useState('1');
  const [preview, setPreview] = useState<FindReplacePreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewSignature, setPreviewSignature] = useState('');
  const [shelves, setShelves] = useState<ShelfOption[]>([]);
  const [shelvesLoading, setShelvesLoading] = useState(false);
  const [shelfId, setShelfId] = useState('');
  const [membership, setMembership] = useState<'ADD' | 'REMOVE'>('ADD');
  const [readingStatus, setReadingStatus] = useState<'UNREAD' | 'FINISHED'>('FINISHED');
  const [coverAction, setCoverAction] = useState<'crop' | 'regenerate' | 'compress' | 'replace'>('crop');
  const [coverRatio, setCoverRatio] = useState('2:3');
  const [coverQuality, setCoverQuality] = useState('82');
  const [coverMaxDimension, setCoverMaxDimension] = useState('1600');
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [deleteSource, setDeleteSource] = useState(false);

  const activeAction = actions.find((item) => item.value === action);
  const findReplaceSignature = useMemo(() => JSON.stringify({ selectedIds, findField, findText, replacement, regex, caseSensitive, startNumber }), [caseSensitive, findField, findText, regex, replacement, selectedIds, startNumber]);
  const previewCurrent = preview !== null && previewSignature === findReplaceSignature;
  const metadataReady = authorEnabled || seriesEnabled || splitValues(addTags).length > 0 || splitValues(removeTags).length > 0;
  const findFieldOptions: SelectOption[] = [
    { value: 'title', label: '书名', group: '作品元数据' },
    { value: 'author', label: '作者', group: '作品元数据' },
    { value: 'description', label: '简介', group: '作品元数据' },
    { value: 'seriesName', label: '系列', group: '作品元数据' },
    { value: 'tags', label: '标签', group: '作品元数据' },
    { value: 'volumeTitle', label: '卷册名称', group: '卷册资源' }
  ];

  useEffect(() => {
    if (!action) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape' && !saving) onClose();
    }
    document.addEventListener('keydown', closeOnEscape);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', closeOnEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [action, onClose, saving]);

  useEffect(() => {
    if (action !== 'shelves' || shelves.length > 0) return;
    let active = true;
    setShelvesLoading(true);
    fetch('/api/shelves')
      .then((response) => response.json() as Promise<{ ok: boolean; data?: { shelves?: ShelfOption[] }; error?: { message?: string } }>)
      .then((payload) => {
        if (!active) return;
        if (!payload.ok) throw new Error(payload.error?.message ?? '读取书架失败');
        const staticShelves = (payload.data?.shelves ?? []).filter((shelf) => (shelf.kind ?? 'STATIC') === 'STATIC');
        setShelves(staticShelves);
        setShelfId((current) => current || staticShelves[0]?.id || '');
      })
      .catch((reason) => active && toast.error('读取书架失败', reason instanceof Error ? reason.message : '请稍后重试'))
      .finally(() => active && setShelvesLoading(false));
    return () => { active = false; };
  }, [action, shelves.length, toast]);

  useEffect(() => {
    if (action !== 'delete') setDeleteSource(false);
  }, [action]);

  if (!action || typeof document === 'undefined') return null;

  async function postJson(body: Record<string, unknown>) {
    const response = await fetch('/api/works/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: selectedIds, ...body })
    });
    const payload = await response.json() as BulkResponse;
    if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '批量操作失败');
    return payload;
  }

  async function applyMetadata() {
    const fields: Record<string, string> = {};
    if (authorEnabled) fields.author = author;
    if (seriesEnabled) fields.seriesName = seriesName;
    const payload = await postJson({ action: 'update_metadata', fields, addTags: splitValues(addTags), removeTags: splitValues(removeTags) });
    return `已更新 ${payload.data?.updated ?? selectedIds.length} 本图书的元数据`;
  }

  function findReplaceBody() {
    return {
      field: findField,
      find: findText,
      replacement,
      regex,
      caseSensitive,
      startNumber: Number(startNumber) || 1
    };
  }

  async function loadPreview() {
    if (!findText) return;
    setPreviewing(true);
    try {
      const signature = findReplaceSignature;
      const response = await fetch('/api/works/bulk/find-replace/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: selectedIds, ...findReplaceBody() })
      });
      const payload = await response.json() as { ok: boolean; data?: FindReplacePreview; error?: { message?: string } };
      if (!response.ok || !payload.ok || !payload.data) throw new Error(payload.error?.message ?? '生成预览失败');
      setPreview(payload.data);
      setPreviewSignature(signature);
    } catch (reason) {
      setPreview(null);
      toast.error('无法生成替换预览', reason instanceof Error ? reason.message : '请检查查找规则');
    } finally {
      setPreviewing(false);
    }
  }

  async function applyFindReplace() {
    const payload = await postJson({ action: 'find_replace', ...findReplaceBody() });
    return `已替换 ${payload.data?.changedValues ?? 0} 处元数据`;
  }

  async function applyShelves() {
    const payload = await postJson({ action: 'shelf_membership', membership, shelfId });
    return membership === 'ADD'
      ? `已将 ${payload.data?.updated ?? selectedIds.length} 本图书加入书架`
      : `已从书架移除 ${payload.data?.updated ?? selectedIds.length} 本图书`;
  }

  async function applyReadingStatus() {
    const payload = await postJson({ action: 'reading_status', status: readingStatus });
    return readingStatus === 'UNREAD'
      ? `已清空 ${payload.data?.updated ?? selectedIds.length} 本图书的阅读记录`
      : `已将 ${payload.data?.updated ?? selectedIds.length} 本图书设为已读`;
  }

  async function applyCovers() {
    const form = new FormData();
    form.append('ids', JSON.stringify(selectedIds));
    form.append('action', coverAction);
    form.append('ratio', coverRatio);
    form.append('quality', coverQuality);
    form.append('maxDimension', coverMaxDimension);
    if (coverFile) form.append('cover', coverFile);
    const response = await fetch('/api/works/bulk/cover', { method: 'POST', body: form });
    const payload = await response.json() as BulkResponse;
    if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '批量处理封面失败');
    const skipped = payload.data?.skipped?.length ?? 0;
    return `已处理 ${payload.data?.updated ?? selectedIds.length} 本图书的封面${skipped ? `，跳过 ${skipped} 本` : ''}`;
  }

  async function applyDelete() {
    const payload = await postJson({ action: 'delete_records', deleteSource });
    const deleted = payload.data?.deleted ?? payload.data?.updated ?? 0;
    const failed = payload.data?.failedFileDeletes?.length ?? 0;
    const message = i18nAttribute('已删除 {value0} 本图书', { value0: deleted });
    return failed > 0
      ? `${message}，${i18nAttribute('有 {value0} 个文件未能删除，请检查系统日志', { value0: failed })}`
      : message;
  }

  async function submit() {
    setSaving(true);
    try {
      const message = action === 'metadata'
        ? await applyMetadata()
        : action === 'find_replace'
          ? await applyFindReplace()
          : action === 'shelves'
            ? await applyShelves()
            : action === 'reading_status'
              ? await applyReadingStatus()
              : action === 'covers'
                ? await applyCovers()
                : await applyDelete();
      toast.success(message);
      onApplied(message);
    } catch (reason) {
      toast.error('批量操作失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setSaving(false);
    }
  }

  const disabled = selectedIds.length === 0
    || (action === 'metadata' && !metadataReady)
    || (action === 'find_replace' && (!previewCurrent || (preview?.changedWorks ?? 0) === 0))
    || (action === 'shelves' && !shelfId)
    || (action === 'covers' && coverAction === 'replace' && !coverFile);

  return createPortal(
    <div
      className="fixed inset-0 z-[120] flex items-end justify-center bg-[#241F1C]/35 p-0 backdrop-blur-[2px] md:items-center md:p-6"
      role="presentation"
      onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}
    >
      <section role="dialog" aria-modal="true" aria-label={activeAction?.label} className="flex max-h-[94dvh] w-full max-w-4xl flex-col overflow-hidden rounded-t-3xl border border-black/[0.08] bg-[#FFFEFC] shadow-[0_30px_90px_rgba(47,37,31,0.25)] md:max-h-[88vh] md:rounded-3xl">
        <header className="shrink-0 border-b border-black/[0.07] px-5 pb-4 pt-5 md:px-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold tracking-[-0.02em] text-[#282421]">{activeAction?.label}</h2>
              <p className="mt-1 text-sm text-[#817A74]"><I18nText>当前操作会应用到已选择的 </I18nText>{selectedIds.length} <I18nText>本图书。</I18nText></p>
            </div>
            <button type="button" disabled={saving} onClick={onClose} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-[#77716B] transition hover:bg-black/[0.05] disabled:opacity-40" aria-label={i18nAttribute("关闭批量操作")}><X size={18} /></button>
          </div>
          <nav className="mt-4 flex gap-1.5 overflow-x-auto pb-1" aria-label={i18nAttribute("批量操作类型")}>
            {actions.filter((item) => canUseLibraryBatchAction(item.value, canManageSystem)).map((item) => {
              const Icon = item.icon;
              const destructive = item.value === 'delete';
              return (
                <button key={item.value} type="button" disabled={saving} onClick={() => onActionChange(item.value)} aria-current={action === item.value ? 'page' : undefined} className={cn(
                  'inline-flex h-10 shrink-0 items-center gap-2 rounded-xl px-3 text-xs font-medium transition',
                  action === item.value
                    ? destructive ? 'bg-red-700 text-white shadow-sm' : 'bg-[#2D2926] text-white shadow-sm'
                    : destructive ? 'bg-red-50 text-red-700 hover:bg-red-100' : 'bg-black/[0.035] text-[#716A64] hover:bg-[#FFF0EA] hover:text-[#D7462B]',
                  'disabled:cursor-not-allowed disabled:opacity-50'
                )}>
                  <Icon size={15} />{item.shortLabel}
                </button>
              );
            })}
          </nav>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-6 md:py-6">
          {action === 'metadata' ? (
            <div className="space-y-3">
              <div className="grid gap-3 md:grid-cols-2">
                <FieldToggle checked={authorEnabled} onChange={setAuthorEnabled} icon={UserRound} label={i18nAttribute("作者")} hint={i18nAttribute("统一覆盖作品作者")}>
                  <input value={author} onChange={(event) => setAuthor(event.target.value)} className={inputClass} placeholder={i18nAttribute("例如：余华")} />
                </FieldToggle>
                <FieldToggle checked={seriesEnabled} onChange={setSeriesEnabled} icon={LibraryBig} label={i18nAttribute("系列")} hint={i18nAttribute("统一设置或留空清除")}>
                  <input value={seriesName} onChange={(event) => setSeriesName(event.target.value)} className={inputClass} placeholder={i18nAttribute("例如：银河帝国")} />
                </FieldToggle>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="rounded-2xl border border-black/[0.07] bg-white/60 p-4 text-sm font-semibold text-[#34302D]"><I18nText>添加标签</I18nText><span className="mt-1 block text-xs font-normal leading-5 text-[#8A837C]"><I18nText>逗号或换行分隔；已有标签不会重复。</I18nText></span>
                  <textarea value={addTags} onChange={(event) => setAddTags(event.target.value)} className={cn(textareaClass, 'mt-3')} placeholder={i18nAttribute("科幻, 待读\n2026 精选")} />
                </label>
                <label className="rounded-2xl border border-black/[0.07] bg-white/60 p-4 text-sm font-semibold text-[#34302D]"><I18nText>删除标签</I18nText><span className="mt-1 block text-xs font-normal leading-5 text-[#8A837C]"><I18nText>按完整标签名匹配，不区分大小写。</I18nText></span>
                  <textarea value={removeTags} onChange={(event) => setRemoveTags(event.target.value)} className={cn(textareaClass, 'mt-3')} placeholder={i18nAttribute("待整理, 临时")} />
                </label>
              </div>
              <p className="rounded-xl bg-[#F6F3EF] px-4 py-3 text-xs leading-5 text-[#777069]"><I18nText>未勾选的字段会保持原值；勾选后留空可清除出版社或系列，作者留空会统一设为“未知作者”。</I18nText></p>
            </div>
          ) : null}

          {action === 'find_replace' ? (
            <div className="space-y-5">
              <div className="grid gap-4 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
                <label className="block text-sm font-medium text-[#4D4843]"><I18nText>查找字段</I18nText><Select value={findField} onChange={(value) => setFindField(value)} options={findFieldOptions} className="mt-2 w-full" menuWidth={320} ariaLabel={i18nAttribute("查找字段")} />
                </label>
                <label className="block text-sm font-medium text-[#4D4843]"><I18nText>查找内容</I18nText><input value={findText} onChange={(event) => setFindText(event.target.value)} className={cn(inputClass, 'mt-2')} placeholder={regex ? i18nAttribute("例如：第\\s*(\\d+)\\s*卷") : i18nAttribute("输入要查找的关键字")} />
                </label>
              </div>
              <label className="block text-sm font-medium text-[#4D4843]"><I18nText>替换为</I18nText><textarea value={replacement} onChange={(event) => setReplacement(event.target.value)} className={cn(textareaClass, 'mt-2 font-mono')} placeholder={i18nAttribute("输入文字，或插入下方安全 Jinja 变量")} />
              </label>
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold text-[#766F69]"><Braces size={14} /><I18nText>插入模板变量</I18nText></div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {[
                    ['{{ match }}', '匹配文字'],
                    ['{{ value }}', '字段原值'],
                    ['{{ number }}', '递增数字'],
                    ['{{ letter_upper }}', '递增字母'],
                    ['{{ index }}', '选择序号']
                  ].map(([token, label]) => <button key={token} type="button" onClick={() => setReplacement((current) => `${current}${token}`)} className="rounded-lg border border-black/[0.08] bg-white px-2.5 py-1.5 font-mono text-[11px] text-[#625C56] transition hover:border-[#F0B4A3] hover:bg-[#FFF3EE] hover:text-[#D7462B]" title={label}>{token}</button>)}
                </div>
              </div>
              <div className="flex flex-col gap-3 rounded-2xl border border-black/[0.07] bg-[#F9F7F4] p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap gap-4">
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-[#5E5853]"><input type="checkbox" checked={regex} onChange={(event) => setRegex(event.target.checked)} className="h-4 w-4 accent-[#EF4D2F]" /><I18nText>正则匹配</I18nText></label>
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-[#5E5853]"><input type="checkbox" checked={caseSensitive} onChange={(event) => setCaseSensitive(event.target.checked)} className="h-4 w-4 accent-[#EF4D2F]" /><I18nText>区分大小写</I18nText></label>
                </div>
                <label className="flex items-center gap-2 text-sm text-[#5E5853]"><Hash size={15} /><I18nText>序列起始值</I18nText><input type="number" min="1" value={startNumber} onChange={(event) => setStartNumber(event.target.value)} className="h-9 w-20 rounded-lg border border-black/[0.1] bg-white px-2 text-center outline-none focus:border-[#E8A18D]" /></label>
              </div>
              <div className="rounded-2xl border border-black/[0.07] bg-white/65 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div><div className="text-sm font-semibold text-[#393531]"><I18nText>替换预览</I18nText></div><div className="mt-1 text-xs text-[#8A837C]"><I18nText>确认前最多展示 30 条实际变化。</I18nText></div></div>
                  <Button variant="secondary" icon={Eye} loading={previewing} loadingText={i18nAttribute("生成中")} disabled={!findText} onClick={() => void loadPreview()}><I18nText>生成预览</I18nText></Button>
                </div>
                {!previewCurrent ? <div className="mt-4 rounded-xl bg-[#F7F4F0] px-4 py-6 text-center text-xs text-[#918A83]"><I18nText>填写规则后生成预览，避免误改元数据。</I18nText></div> : preview && preview.changedWorks === 0 ? <div className="mt-4 rounded-xl bg-amber-50 px-4 py-4 text-sm text-amber-800"><I18nText>没有找到匹配内容，不会修改任何图书。</I18nText></div> : preview ? (
                  <div className="mt-4">
                    <div className="mb-2 text-xs font-medium text-[#777069]"><I18nText>将修改 </I18nText>{preview.changedWorks} <I18nText>本图书，共 </I18nText>{preview.changedValues} <I18nText>处</I18nText></div>
                    <div className="max-h-64 space-y-2 overflow-auto pr-1">
                      {preview.items.map((item, index) => (
                        <div key={`${item.workId}-${index}`} className="rounded-xl border border-black/[0.06] bg-[#FAF8F5] px-3 py-2.5">
                          <div className="truncate text-xs font-semibold text-[#45403C]">{item.title}</div>
                          <div className="mt-1 grid gap-1 text-xs sm:grid-cols-[1fr_auto_1fr] sm:items-center">
                            <span className="break-words text-[#918A83] line-through">{valueLabel(item.before)}</span>
                            <span className="hidden text-[#B2ABA4] sm:block">→</span>
                            <span className="break-words font-medium text-[#D7462B]">{valueLabel(item.after)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}

          {action === 'shelves' ? (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3">
                {([['ADD', '加入书架', '保留已有书架归属'], ['REMOVE', '移除书架', '只移除指定书架归属']] as const).map(([value, label, description]) => (
                  <button key={value} type="button" onClick={() => setMembership(value)} className={cn('rounded-2xl border p-4 text-left transition', membership === value ? 'border-[#EFAE9B] bg-[#FFF3EE] ring-2 ring-[#FFE2D8]' : 'border-black/[0.08] bg-white hover:bg-black/[0.02]')}>
                    <span className="flex items-center justify-between text-sm font-semibold text-[#37322F]">{i18nAttribute(label)}{membership === value ? <Check size={16} className="text-[#EF4D2F]" /> : null}</span>
                    <span className="mt-1.5 block text-xs leading-5 text-[#837C75]">{description}</span>
                  </button>
                ))}
              </div>
              <label className="block text-sm font-medium text-[#4D4843]"><I18nText>目标书架</I18nText><Select value={shelfId} onChange={setShelfId} options={shelves.map((shelf) => ({ value: shelf.id, label: shelf.name, translate: false }))} placeholder={shelvesLoading ? i18nAttribute("正在读取书架…") : shelves.length ? i18nAttribute("请选择普通书架") : i18nAttribute("暂无普通书架")} disabled={shelvesLoading || shelves.length === 0} className="mt-2 w-full" menuWidth={420} ariaLabel={i18nAttribute("目标书架")} />
              </label>
              {shelves.length === 0 && !shelvesLoading ? <div className="rounded-xl bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800"><I18nText>当前没有普通书架。请先在书架管理中创建普通书架，智能书架会按规则自动更新，不能手动加入。</I18nText></div> : null}
            </div>
          ) : null}

          {action === 'reading_status' ? (
            <div className="grid gap-4 md:grid-cols-2">
              <button type="button" onClick={() => setReadingStatus('UNREAD')} className={cn('rounded-2xl border p-5 text-left transition', readingStatus === 'UNREAD' ? 'border-[#EFAE9B] bg-[#FFF3EE] ring-2 ring-[#FFE2D8]' : 'border-black/[0.08] bg-white hover:bg-black/[0.02]')}>
                <span className="flex items-center justify-between text-base font-semibold text-[#37322F]"><I18nText>设为未读</I18nText>{readingStatus === 'UNREAD' ? <Check size={18} className="text-[#EF4D2F]" /> : null}</span>
                <span className="mt-3 block text-sm leading-6 text-[#746D67]"><I18nText>清空当前用户在这些图书中的全部阅读位置、页码、进度和媒介阅读状态。操作后进度从 0% 重新开始。</I18nText></span>
              </button>
              <button type="button" onClick={() => setReadingStatus('FINISHED')} className={cn('rounded-2xl border p-5 text-left transition', readingStatus === 'FINISHED' ? 'border-[#EFAE9B] bg-[#FFF3EE] ring-2 ring-[#FFE2D8]' : 'border-black/[0.08] bg-white hover:bg-black/[0.02]')}>
                <span className="flex items-center justify-between text-base font-semibold text-[#37322F]"><I18nText>设为已读</I18nText>{readingStatus === 'FINISHED' ? <Check size={18} className="text-[#EF4D2F]" /> : null}</span>
                <span className="mt-3 block text-sm leading-6 text-[#746D67]"><I18nText>将所有可见卷册的阅读进度更新为 100%；作品完成状态会据此动态计算。</I18nText></span>
              </button>
            </div>
          ) : null}

          {action === 'covers' ? (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {([
                  ['crop', '封面裁剪', '按统一比例居中裁剪', Scissors],
                  ['regenerate', '重新生成', '从卷册资源恢复封面', RotateCcw],
                  ['compress', '封面压缩', '降低尺寸和文件体积', Minimize2],
                  ['replace', '替换封面', '使用同一张新图片', ImagePlus]
                ] as const).map(([value, label, description, Icon]) => (
                  <button key={value} type="button" onClick={() => setCoverAction(value)} className={cn('rounded-2xl border p-4 text-left transition', coverAction === value ? 'border-[#EFAE9B] bg-[#FFF3EE] ring-2 ring-[#FFE2D8]' : 'border-black/[0.08] bg-white hover:bg-black/[0.02]')}>
                    <span className="flex items-center justify-between"><Icon size={18} className={coverAction === value ? 'text-[#EF4D2F]' : 'text-[#756E68]'} />{coverAction === value ? <Check size={15} className="text-[#EF4D2F]" /> : null}</span>
                    <span className="mt-3 block text-sm font-semibold text-[#37322F]">{i18nAttribute(label)}</span>
                    <span className="mt-1 block text-[11px] leading-5 text-[#837C75]">{description}</span>
                  </button>
                ))}
              </div>
              {coverAction === 'crop' ? (
                <label className="block rounded-2xl border border-black/[0.07] bg-white/70 p-4 text-sm font-medium text-[#4D4843]"><I18nText>目标比例</I18nText><Select value={coverRatio} onChange={setCoverRatio} options={[{ value: '2:3', label: '2:3 · 常用图书封面' }, { value: '3:4', label: '3:4 · 宽版封面' }, { value: '1:1', label: '1:1 · 方形封面' }]} className="mt-2 w-full" ariaLabel={i18nAttribute("封面裁剪比例")} />
                  <span className="mt-2 block text-xs font-normal leading-5 text-[#8A837C]"><I18nText>以每张当前封面的中心为焦点裁剪，原始文件不会被改写。</I18nText></span>
                </label>
              ) : null}
              {coverAction === 'replace' ? (
                <label className={cn('flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-5 py-8 text-center transition', coverFile ? 'border-[#EFAE9B] bg-[#FFF5F1]' : 'border-black/[0.14] bg-white hover:border-[#EFAE9B] hover:bg-[#FFF9F6]')}>
                  <ImagePlus size={24} className="text-[#EF4D2F]" />
                  <span className="mt-3 text-sm font-semibold text-[#3F3A36]">{coverFile ? coverFile.name : i18nAttribute("选择一张替换封面")}</span>
                  <span className="mt-1 text-xs leading-5 text-[#8A837C]"><I18nText>支持 JPEG、PNG、WEBP，最大 12 MB；会应用到全部已选图书。</I18nText></span>
                  <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={(event) => setCoverFile(event.target.files?.[0] ?? null)} />
                </label>
              ) : null}
              {coverAction === 'compress' || coverAction === 'replace' ? (
                <div className="grid gap-4 rounded-2xl border border-black/[0.07] bg-[#F9F7F4] p-4 sm:grid-cols-2">
                  <label className="text-sm font-medium text-[#4D4843]"><I18nText>JPEG 质量</I18nText><div className="mt-2 flex items-center gap-3"><input type="range" min="40" max="95" value={coverQuality} onChange={(event) => setCoverQuality(event.target.value)} className="h-2 flex-1 accent-[#EF4D2F]" /><span className="w-10 text-right text-sm tabular-nums text-[#635D57]">{coverQuality}</span></div>
                  </label>
                  <label className="text-sm font-medium text-[#4D4843]"><I18nText>最长边</I18nText><Select value={coverMaxDimension} onChange={setCoverMaxDimension} options={[{ value: '1200', label: '1200 px · 更小体积' }, { value: '1600', label: '1600 px · 推荐' }, { value: '2400', label: '2400 px · 高清' }, { value: '3200', label: '3200 px · 原图优先' }]} className="mt-2 w-full" ariaLabel={i18nAttribute("封面最长边")} />
                  </label>
                </div>
              ) : null}
              {coverAction === 'regenerate' ? <div className="rounded-xl bg-[#F6F3EF] px-4 py-3 text-sm leading-6 text-[#706963]"><I18nText>系统会按媒介优先级和卷册顺序恢复已提取的封面；找不到可用封面时使用默认封面。上传的自定义封面会被替换。</I18nText></div> : null}
            </div>
          ) : null}

          {action === 'delete' ? (
            <div className="space-y-5">
              <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-red-900">
                <div className="flex items-start gap-3">
                  <Trash2 size={20} className="mt-0.5 shrink-0 text-red-600" />
                  <div>
                    <div className="font-semibold"><I18nText>删除所选图书</I18nText></div>
                    <p className="mt-1 text-sm leading-6 text-red-800"><I18nText>删除后，所选图书的书库记录、阅读进度、书签和系统生成文件将无法恢复。</I18nText></p>
                  </div>
                </div>
              </div>
              <label className={cn('flex cursor-pointer gap-3 rounded-2xl border p-4 transition', deleteSource ? 'border-red-200 bg-red-50' : 'border-black/[0.08] bg-black/[0.02] hover:bg-black/[0.04]')}>
                <input type="checkbox" checked={deleteSource} disabled={saving} onChange={(event) => setDeleteSource(event.target.checked)} className="mt-0.5 h-4 w-4 accent-red-600" />
                <span>
                  <span className="block text-sm font-semibold text-[#302C29]"><I18nText>同步删除源文件</I18nText></span>
                  <span className="mt-1 block text-xs leading-5 text-[#77716B]"><I18nText>源文件将从监控或上传目录中永久删除；该操作无法恢复。</I18nText></span>
                </span>
              </label>
              {!deleteSource ? <p className="rounded-xl bg-[#F6F3EF] px-4 py-3 text-sm text-[#706963]"><I18nText>来源文件将保留，只删除书库记录和系统生成文件。</I18nText></p> : null}
            </div>
          ) : null}
        </div>

        <footer className="flex shrink-0 flex-col gap-3 border-t border-black/[0.07] bg-[#FFFEFC] px-5 py-4 sm:flex-row sm:items-center sm:justify-between md:px-6">
          <div className="text-xs leading-5 text-[#837C75]"><I18nText>仅处理当前已选择的 </I18nText>{selectedIds.length} <I18nText>本图书；未选择的项目不会变化。</I18nText></div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" disabled={saving} onClick={onClose}><I18nText>取消</I18nText></Button>
            <Button type="button" variant={action === 'delete' ? 'danger' : 'primary'} icon={action === 'delete' ? Trash2 : undefined} loading={saving} loadingText={action === 'delete' ? i18nAttribute("删除中") : i18nAttribute("正在处理")} disabled={disabled} onClick={() => void submit()}>
              {action === 'find_replace' ? i18nAttribute("确认替换") : action === 'delete' ? i18nAttribute("确认删除") : i18nAttribute("应用更改")}
            </Button>
          </div>
        </footer>
      </section>
    </div>,
    document.body
  );
}
