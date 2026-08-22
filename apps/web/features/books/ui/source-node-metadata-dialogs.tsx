'use client';

import { ImagePlus, Search, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Cover } from '../../../components/book/cover';
import { Button } from '../../../components/ui/button';
import { Select } from '../../../components/ui/select';
import { useToast } from '../../../components/ui/feedback';
import { I18nText, useI18n } from '../../../i18n/provider';
import type { BookView } from '../../../types/book';
import { searchSourceNodeMetadata, updateSourceNodeMetadata, updateSourceNodePresentation } from '../api/client';
import type { BookContentEntry, SourceNodeMetadataCandidate } from '../model/book-contents';

type SharedProps = Readonly<{
  bookId: string;
  entry: BookContentEntry | null;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}>;

type EditorProps = SharedProps & Readonly<{
  book: BookView;
  fallbackCoverUrl: string | null;
}>;

export function SourceNodeMetadataEditor({ bookId, book, entry, fallbackCoverUrl, onClose, onSaved }: EditorProps) {
  const feedback = useToast();
  const { t } = useI18n();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [removeCover, setRemoveCover] = useState(false);
  const [coverPreviewUrl, setCoverPreviewUrl] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const coverInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTitle(entry?.title ?? '');
    setDescription(entry?.description ?? '');
    setCoverFile(null);
    setRemoveCover(false);
  }, [entry]);
  useEffect(() => {
    if (!coverFile) {
      setCoverPreviewUrl(null);
      return;
    }
    const previewUrl = URL.createObjectURL(coverFile);
    setCoverPreviewUrl(previewUrl);
    return () => URL.revokeObjectURL(previewUrl);
  }, [coverFile]);
  if (!entry) return null;

  const save = async () => {
    if (!title.trim()) return;
    setSaving(true);
    try {
      await updateSourceNodePresentation(bookId, entry.sourceNodeId, {
        title: title.trim(),
        description: description.trim() || null,
        cover: coverFile,
        removeCover
      });
      await onSaved();
      feedback.success(t('版本信息已保存'));
      onClose();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setSaving(false);
    }
  };

  return <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/45 md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('编辑版本')}>
    <div className="w-full max-w-xl rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>编辑版本</I18nText></h2><button type="button" onClick={onClose} aria-label={t('关闭')}><X size={20} /></button></div>
      <div className="mt-5 grid gap-5 md:grid-cols-[140px_minmax(0,1fr)]">
        <div>
          <div className="text-sm text-stone-600"><I18nText>目录封面</I18nText></div>
          <Cover book={{ id: entry.sourceNodeId, title: entry.title, author: book.author, coverUrl: coverPreviewUrl || (!removeCover ? entry.coverUrl : null) || fallbackCoverUrl || book.coverUrl, gradient: book.gradient, coverStatus: '' }} className="mt-1.5 aspect-[2/3] w-full rounded-xl shadow-sm" size="small" />
          <input ref={coverInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(event) => { const file = event.target.files?.[0] ?? null; setCoverFile(file); if (file) setRemoveCover(false); event.currentTarget.value = ''; }} />
          <div className="mt-3 grid gap-2">
            <Button variant="secondary" icon={ImagePlus} className="!min-h-9 !rounded-lg !px-3 text-xs" onClick={() => coverInputRef.current?.click()}><I18nText>{entry.coverUrl || coverFile ? '更换封面' : '选择封面'}</I18nText></Button>
            {entry.coverUrl || coverFile ? <Button variant="secondary" icon={Trash2} className="!min-h-9 !rounded-lg !px-3 text-xs" onClick={() => { setCoverFile(null); setRemoveCover(Boolean(entry.coverUrl)); }}><I18nText>移除独立封面</I18nText></Button> : null}
          </div>
          <p className="mt-2 text-xs leading-5 text-stone-500"><I18nText>未单独设置时沿用图书卷或图书封面</I18nText></p>
        </div>
        <div className="grid content-start gap-4">
          <label className="text-sm text-stone-600"><I18nText>标题</I18nText><input value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1.5 w-full rounded-xl border border-stone-200 px-3 py-2.5" /></label>
          <label className="text-sm text-stone-600"><I18nText>简介</I18nText><textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={5} className="mt-1.5 w-full resize-y rounded-xl border border-stone-200 px-3 py-2.5" /></label>
        </div>
      </div>
      <div className="mt-6 flex justify-end gap-2"><Button variant="secondary" onClick={onClose}><I18nText>取消</I18nText></Button><Button loading={saving} disabled={!title.trim()} onClick={() => void save()}><I18nText>保存</I18nText></Button></div>
    </div>
  </div>;
}

export function SourceNodeMetadataRecognitionDialog({ bookId, entry, onClose, onSaved }: SharedProps) {
  const feedback = useToast();
  const { t } = useI18n();
  const [providerId, setProviderId] = useState('douban');
  const [query, setQuery] = useState('');
  const [candidates, setCandidates] = useState<SourceNodeMetadataCandidate[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setQuery(entry?.title ?? '');
    setCandidates([]);
    setMessage('');
  }, [entry]);
  if (!entry) return null;

  const search = async () => {
    setBusy(true);
    setMessage('');
    try {
      const result = await searchSourceNodeMetadata(bookId, entry.sourceNodeId, providerId, query.trim());
      setCandidates(result.candidates);
      setMessage(result.candidates.length ? t('找到 {value0} 条候选', { value0: result.candidates.length }) : result.message || t('没有找到候选'));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('元数据识别失败'));
    } finally {
      setBusy(false);
    }
  };

  const apply = async (candidate: SourceNodeMetadataCandidate) => {
    setBusy(true);
    try {
      await updateSourceNodeMetadata(bookId, entry.sourceNodeId, {
        title: candidate.title?.trim() || entry.title,
        description: candidate.description?.trim() || entry.description
      });
      await onSaved();
      feedback.success(t('识别结果已应用到版本'));
      onClose();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setBusy(false);
    }
  };

  return <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/45 md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('识别版本元数据')}>
    <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>识别版本元数据</I18nText></h2><button type="button" onClick={onClose} aria-label={t('关闭')}><X size={20} /></button></div>
      <div className="mt-5 flex flex-col gap-3 sm:flex-row">
        <Select value={providerId} ariaLabel="元数据来源" options={[{ value: 'douban', label: '豆瓣图书' }, { value: 'bangumi', label: 'Bangumi 漫画' }, { value: 'ai', label: 'AI 元数据识别' }]} onChange={setProviderId} className="sm:w-44" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} className="min-w-0 flex-1 rounded-xl border border-stone-200 px-3 py-2.5" aria-label={t('识别关键词')} />
        <Button icon={Search} loading={busy} disabled={!query.trim()} onClick={() => void search()}><I18nText>搜索</I18nText></Button>
      </div>
      {message ? <p className="mt-4 text-sm text-stone-500">{message}</p> : null}
      <div className="mt-4 grid gap-3">{candidates.map((candidate) => <article key={`${candidate.source}:${candidate.id}`} className="rounded-2xl border border-stone-200 p-4"><div className="flex items-start justify-between gap-4"><div className="min-w-0"><h3 data-i18n-skip className="font-semibold text-stone-900">{candidate.title || entry.title}</h3>{candidate.description ? <p data-i18n-skip className="mt-2 line-clamp-3 text-sm leading-6 text-stone-600">{candidate.description}</p> : null}<p data-i18n-skip className="mt-2 text-xs text-stone-400">{candidate.source}</p></div><Button variant="secondary" disabled={busy} onClick={() => void apply(candidate)}><I18nText>应用</I18nText></Button></div></article>)}</div>
      <div className="mt-6 flex justify-end"><Button variant="secondary" onClick={onClose}><I18nText>关闭</I18nText></Button></div>
    </div>
  </div>;
}
