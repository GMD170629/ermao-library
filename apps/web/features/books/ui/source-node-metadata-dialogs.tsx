'use client';

import { ImagePlus, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Cover } from '../../../components/book/cover';
import { Button } from '../../../components/ui/button';
import { useToast } from '../../../components/ui/feedback';
import { I18nText, useI18n } from '../../../i18n/provider';
import type { BookView } from '../../../types/book';
import { updateSourceNodePresentation } from '../api/client';
import type { BookContentEntry } from '../model/book-contents';
import { MetadataLookupModal } from '../metadata-lookup-modal';

type SharedProps = Readonly<{
  bookId: string;
  entry: BookContentEntry | null;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}>;

type EditorProps = SharedProps & Readonly<{
  book: BookView;
}>;

export function SourceNodeMetadataEditor({ bookId, book, entry, onClose, onSaved }: EditorProps) {
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
      feedback.success(t('来源目录信息已保存'));
      onClose();
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('操作失败'));
    } finally {
      setSaving(false);
    }
  };

  return <div className="fixed inset-0 z-[120] flex items-end justify-center bg-black/45 md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('编辑来源目录')}>
    <div className="w-full max-w-xl rounded-t-3xl bg-white p-5 shadow-2xl md:rounded-3xl">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold"><I18nText>编辑来源目录</I18nText></h2><button type="button" onClick={onClose} aria-label={t('关闭')}><X size={20} /></button></div>
      <div className="mt-5 grid gap-5 md:grid-cols-[140px_minmax(0,1fr)]">
        <div>
          <div className="text-sm text-stone-600"><I18nText>目录封面</I18nText></div>
          <Cover book={{ id: entry.sourceNodeId, title: entry.title, author: book.author, coverUrl: coverPreviewUrl || (!removeCover ? entry.coverUrl : null) || '', gradient: book.gradient, coverStatus: '' }} className="mt-1.5 aspect-[2/3] w-full rounded-xl shadow-sm" size="small" />
          <input ref={coverInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(event) => { const file = event.target.files?.[0] ?? null; setCoverFile(file); if (file) setRemoveCover(false); event.currentTarget.value = ''; }} />
          <div className="mt-3 grid gap-2">
            <Button variant="secondary" icon={ImagePlus} className="!min-h-9 !rounded-lg !px-3 text-xs" onClick={() => coverInputRef.current?.click()}><I18nText>{entry.coverUrl || coverFile ? '更换封面' : '选择封面'}</I18nText></Button>
            {entry.coverUrl || coverFile ? <Button variant="secondary" icon={Trash2} className="!min-h-9 !rounded-lg !px-3 text-xs" onClick={() => { setCoverFile(null); setRemoveCover(Boolean(entry.coverUrl)); }}><I18nText>移除独立封面</I18nText></Button> : null}
          </div>
          <p className="mt-2 text-xs leading-5 text-stone-500"><I18nText>未单独设置时沿用可读资源或图书封面</I18nText></p>
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

export function SourceNodeMetadataRecognitionDialog({ book, entry, onClose, onSaved }: EditorProps) {
  if (!entry) return null;
  return <MetadataLookupModal book={book} sourceNodeId={entry.sourceNodeId} currentResourceId={entry.resourceId}
    fixedScope={entry.resourceId ? 'resource' : 'book'} open onClose={onClose} onApplied={onSaved} />;
}
