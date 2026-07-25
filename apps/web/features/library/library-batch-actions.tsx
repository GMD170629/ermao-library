'use client';

import type {
  BulkMutationResponse,
  BulkProgressResponse,
  FindReplacePreviewResponse,
  Page_ShelfResponse_
} from '@/generated/api-v2';
import { apiV2Request } from '@/lib/api-v2';

import {
  BookCheck,
  Braces,
  Building2,
  Check,
  Eye,
  Hash,
  ImagePlus,
  Images,
  LibraryBig,
  Replace,
  Tags,
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

export type LibraryBatchAction = 'metadata' | 'find_replace' | 'shelves' | 'reading_status' | 'covers';

type ContextPosition = { x: number; y: number };
type ShelfOption = Page_ShelfResponse_['items'][number];
type FindReplacePreview = FindReplacePreviewResponse;

const actions: Array<{ value: LibraryBatchAction; label: string; shortLabel: string; description: string; icon: LucideIcon }> = [
  { value: 'metadata', label: '批量更新元数据', shortLabel: '元数据', description: '作者、出版社、标签和系列', icon: Tags },
  { value: 'find_replace', label: '查找替换', shortLabel: '查找替换', description: '支持安全 Jinja 变量和递增序列', icon: Replace },
  { value: 'shelves', label: '加入或移除书架', shortLabel: '书架', description: '管理普通书架中的批量归属', icon: LibraryBig },
  { value: 'reading_status', label: '设置阅读状态', shortLabel: '阅读状态', description: '清空进度或统一设为 100%', icon: BookCheck },
  { value: 'covers', label: '批量替换封面', shortLabel: '封面', description: '使用同一张图片替换所选作品封面', icon: Images }
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
  const height = 392;
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
        {actions.filter((item) => canManageSystem || item.value === 'shelves' || item.value === 'reading_status').map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.value}
              type="button"
              role="menuitem"
              onClick={() => onSelect(item.value)}
              className="group flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left outline-none transition hover:bg-[#FFF2ED] focus-visible:bg-[#FFF2ED]"
            >
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-black/[0.035] text-[#746D67] transition group-hover:bg-white group-hover:text-[#EF4D2F]">
                <Icon size={16} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium text-[#302C29]">{i18nAttribute(item.label)}</span>
                <span className="mt-0.5 block truncate text-[11px] text-[#8B847D]">{i18nAttribute(item.description)}</span>
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
  const [publisherEnabled, setPublisherEnabled] = useState(false);
  const [seriesEnabled, setSeriesEnabled] = useState(false);
  const [author, setAuthor] = useState('');
  const [publisher, setPublisher] = useState('');
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
  const [coverFile, setCoverFile] = useState<File | null>(null);

  const activeAction = actions.find((item) => item.value === action);
  const findReplaceSignature = useMemo(() => JSON.stringify({ selectedIds, findField, findText, replacement, regex, caseSensitive, startNumber }), [caseSensitive, findField, findText, regex, replacement, selectedIds, startNumber]);
  const previewCurrent = preview !== null && previewSignature === findReplaceSignature;
  const metadataReady = authorEnabled || publisherEnabled || seriesEnabled || splitValues(addTags).length > 0 || splitValues(removeTags).length > 0;
  const findFieldOptions: SelectOption[] = [
    { value: 'title', label: '书名', group: '作品元数据' },
    { value: 'author', label: '作者', group: '作品元数据' },
    { value: 'description', label: '简介', group: '作品元数据' },
    { value: 'seriesName', label: '系列', group: '作品元数据' },
    { value: 'tags', label: '标签', group: '作品元数据' },
    { value: 'publisher', label: '出版社（主版本）', group: '版本元数据' },
    { value: 'versionName', label: '版本名称（主版本）', group: '版本元数据' },
    { value: 'language', label: '语言（主版本）', group: '版本元数据' },
    { value: 'isbn', label: 'ISBN（主版本）', group: '版本元数据' },
    { value: 'identifier', label: '外部标识（主版本）', group: '版本元数据' },
    { value: 'narrator', label: '演播者（主版本）', group: '版本元数据' }
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
    apiV2Request<Page_ShelfResponse_>('/api/v2/catalog/shelves')
      .then((payload) => {
        if (!active) return;
        const staticShelves = payload.items.filter((shelf) => shelf.kind === 'manual');
        setShelves(staticShelves);
        setShelfId((current) => current || staticShelves[0]?.id || '');
      })
      .catch((reason) => active && toast.error('读取书架失败', reason instanceof Error ? reason.message : '请稍后重试'))
      .finally(() => active && setShelvesLoading(false));
    return () => { active = false; };
  }, [action, shelves.length, toast]);

  if (!action || typeof document === 'undefined') return null;

  async function postJson<T>(path: string, body: Record<string, unknown>) {
    return apiV2Request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  }

  async function applyMetadata() {
    const payload = await postJson<BulkMutationResponse>(
      '/api/v2/catalog/works/bulk/metadata',
      {
        workIds: selectedIds,
        author: authorEnabled ? author : undefined,
        publisher: publisherEnabled ? publisher : undefined,
        seriesName: seriesEnabled ? seriesName : undefined,
        addTags: splitValues(addTags),
        removeTags: splitValues(removeTags)
      }
    );
    return i18nAttribute('已更新 {count} 本图书的元数据', { count: payload.updated });
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
      const payload = await postJson<FindReplacePreview>(
        '/api/v2/catalog/works/bulk/find-replace/preview',
        { workIds: selectedIds, ...findReplaceBody() }
      );
      setPreview(payload);
      setPreviewSignature(signature);
    } catch (reason) {
      setPreview(null);
      toast.error('无法生成替换预览', reason instanceof Error ? reason.message : '请检查查找规则');
    } finally {
      setPreviewing(false);
    }
  }

  async function applyFindReplace() {
    const payload = await postJson<BulkMutationResponse>(
      '/api/v2/catalog/works/bulk/find-replace',
      { workIds: selectedIds, ...findReplaceBody() }
    );
    return i18nAttribute('已替换 {count} 处元数据', { count: payload.changedValues });
  }

  async function applyShelves() {
    const payload = await postJson<BulkMutationResponse>(
      `/api/v2/catalog/shelves/${shelfId}/works/bulk`,
      { workIds: selectedIds, present: membership === 'ADD' }
    );
    return membership === 'ADD'
      ? i18nAttribute('已将 {count} 本图书加入书架', { count: payload.updated })
      : i18nAttribute('已从书架移除 {count} 本图书', { count: payload.updated });
  }

  async function applyReadingStatus() {
    const payload = await postJson<BulkProgressResponse>(
      '/api/v2/reading/progress/bulk',
      { workIds: selectedIds, status: readingStatus }
    );
    return readingStatus === 'UNREAD'
      ? i18nAttribute('已清空 {count} 本图书的阅读进度', { count: payload.updated })
      : i18nAttribute('已将 {count} 本图书设为已读', { count: payload.updated });
  }

  async function applyCovers() {
    if (!coverFile) throw new Error(i18nAttribute('请选择替换封面'));
    const form = new FormData();
    selectedIds.forEach((id) => form.append('workIds', id));
    form.append('cover', coverFile);
    const payload = await apiV2Request<BulkMutationResponse>(
      '/api/v2/catalog/works/bulk/cover',
      { method: 'POST', body: form }
    );
    return payload.skipped.length
      ? i18nAttribute('已替换 {count} 本图书的封面，跳过 {skipped} 本', {
        count: payload.updated,
        skipped: payload.skipped.length
      })
      : i18nAttribute('已替换 {count} 本图书的封面', { count: payload.updated });
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
              : await applyCovers();
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
    || (action === 'covers' && !coverFile);

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
              <h2 className="text-xl font-semibold tracking-[-0.02em] text-[#282421]">{activeAction ? i18nAttribute(activeAction.label) : ''}</h2>
              <p className="mt-1 text-sm text-[#817A74]"><I18nText>当前操作会应用到已选择的 </I18nText>{selectedIds.length} <I18nText>本图书。</I18nText></p>
            </div>
            <button type="button" disabled={saving} onClick={onClose} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-[#77716B] transition hover:bg-black/[0.05] disabled:opacity-40" aria-label={i18nAttribute("关闭批量操作")}><X size={18} /></button>
          </div>
          <nav className="mt-4 flex gap-1.5 overflow-x-auto pb-1" aria-label={i18nAttribute("批量操作类型")}>
            {actions.filter((item) => canManageSystem || item.value === 'shelves' || item.value === 'reading_status').map((item) => {
              const Icon = item.icon;
              return (
                <button key={item.value} type="button" onClick={() => onActionChange(item.value)} aria-current={action === item.value ? 'page' : undefined} className={cn('inline-flex h-10 shrink-0 items-center gap-2 rounded-xl px-3 text-xs font-medium transition', action === item.value ? 'bg-[#2D2926] text-white shadow-sm' : 'bg-black/[0.035] text-[#716A64] hover:bg-[#FFF0EA] hover:text-[#D7462B]')}>
                  <Icon size={15} />{item.shortLabel}
                </button>
              );
            })}
          </nav>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-6 md:py-6">
          {action === 'metadata' ? (
            <div className="space-y-3">
              <div className="grid gap-3 md:grid-cols-3">
                <FieldToggle checked={authorEnabled} onChange={setAuthorEnabled} icon={UserRound} label={i18nAttribute("作者")} hint={i18nAttribute("统一覆盖作品作者")}>
                  <input value={author} onChange={(event) => setAuthor(event.target.value)} className={inputClass} placeholder={i18nAttribute("例如：余华")} />
                </FieldToggle>
                <FieldToggle checked={publisherEnabled} onChange={setPublisherEnabled} icon={Building2} label={i18nAttribute("出版社")} hint={i18nAttribute("更新每本书的主版本")}>
                  <input value={publisher} onChange={(event) => setPublisher(event.target.value)} className={inputClass} placeholder={i18nAttribute("例如：人民文学出版社")} />
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
                    <span className="mt-1.5 block text-xs leading-5 text-[#837C75]">{i18nAttribute(description)}</span>
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
                <span className="mt-3 block text-sm leading-6 text-[#746D67]"><I18nText>把电子书、漫画和有声书的阅读状态统一设为已完成，并将所有版本的阅读进度更新为 100%。</I18nText></span>
              </button>
            </div>
          ) : null}

          {action === 'covers' ? (
            <div className="space-y-5">
              <label className={cn('flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-5 py-10 text-center transition', coverFile ? 'border-[#EFAE9B] bg-[#FFF5F1]' : 'border-black/[0.14] bg-white hover:border-[#EFAE9B] hover:bg-[#FFF9F6]')}>
                <ImagePlus size={26} className="text-[#EF4D2F]" />
                <span className="mt-3 text-sm font-semibold text-[#3F3A36]">{coverFile ? coverFile.name : i18nAttribute("选择一张替换封面")}</span>
                <span className="mt-1 text-xs leading-5 text-[#8A837C]"><I18nText>支持 JPEG、PNG、WEBP，最大 20 MiB；系统会生成隔离的响应式封面版本，并应用到全部已选图书。</I18nText></span>
                <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={(event) => setCoverFile(event.target.files?.[0] ?? null)} />
              </label>
              <div className="rounded-xl bg-[#F6F3EF] px-4 py-3 text-sm leading-6 text-[#706963]"><I18nText>提交成功前会保留原封面；任何数据库更新失败时，新封面不会进入有效书库状态。</I18nText></div>
            </div>
          ) : null}
        </div>

        <footer className="flex shrink-0 flex-col gap-3 border-t border-black/[0.07] bg-[#FFFEFC] px-5 py-4 sm:flex-row sm:items-center sm:justify-between md:px-6">
          <div className="text-xs leading-5 text-[#837C75]"><I18nText>仅处理当前已选择的 </I18nText>{selectedIds.length} <I18nText>本图书；未选择的项目不会变化。</I18nText></div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" disabled={saving} onClick={onClose}><I18nText>取消</I18nText></Button>
            <Button type="button" loading={saving} loadingText={i18nAttribute("正在处理")} disabled={disabled} onClick={() => void submit()}>
              {action === 'find_replace' ? i18nAttribute("确认替换") : i18nAttribute("应用更改")}
            </Button>
          </div>
        </footer>
      </section>
    </div>,
    document.body
  );
}
