'use client';

import { ImagePlus, Save, Trash2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Cover } from '../../../components/book/cover';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import { useToast } from '../../../components/ui/feedback';
import type { BookView } from '../../../types/book';
import { I18nText, useI18n } from '@/i18n/provider';
import { LibraryTagInput } from '../../library/public';
import {
  BookMetadataSaveError,
  saveBookMetadata,
  type BookCoverChange
} from '../application/save-book-metadata';

type BookForm = Readonly<{
  title: string;
  author: string;
  description: string;
  seriesName: string;
  seriesIndex: string;
  tags: string[];
}>;

function formForBook(book: BookView): BookForm {
  return {
    title: book.title,
    author: book.author,
    description: book.description,
    seriesName: book.seriesName ?? '',
    seriesIndex: book.seriesIndex === null ? '' : String(book.seriesIndex),
    tags: [...book.tags]
  };
}

const inputClassName = 'mt-2 w-full rounded-xl border border-stone-200 bg-white px-4 py-3 text-stone-900 outline-none transition focus:border-orange-300 focus:ring-4 focus:ring-orange-100/70';

export function BookMetadataEditor({
  book,
  open,
  onClose,
  onSaved
}: {
  book: BookView;
  open: boolean;
  onClose: () => void;
  onSaved: (book: BookView) => void;
}) {
  const feedback = useToast();
  const { t } = useI18n();
  const [form, setForm] = useState<BookForm>(() => formForBook(book));
  const [coverChange, setCoverChange] = useState<BookCoverChange>({ kind: 'keep' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(formForBook(book));
    setCoverChange({ kind: 'keep' });
  }, [book, open]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previousOverflow; };
  }, [open]);

  if (!open || typeof document === 'undefined') return null;

  async function save() {
    const title = form.title.trim();
    const parsedSeriesIndex = form.seriesIndex.trim() ? Number(form.seriesIndex) : null;
    if (!title) {
      feedback.error(t('标题不能为空'));
      return;
    }
    if (parsedSeriesIndex !== null && !Number.isFinite(parsedSeriesIndex)) {
      feedback.error(t('系列序号必须是有效数字'));
      return;
    }
    setSaving(true);
    try {
      const nextBook = await saveBookMetadata(book, {
        title,
        author: form.author.trim(),
        description: form.description.trim(),
        seriesName: form.seriesName.trim() || null,
        seriesIndex: parsedSeriesIndex,
        tags: form.tags,
        cover: coverChange
      });
      onSaved(nextBook);
      feedback.success(t('图书信息已保存'));
      onClose();
    } catch (reason) {
      const stageMessage = reason instanceof BookMetadataSaveError
        ? {
            metadata: '图书元数据保存失败，尚未处理标签和封面',
            tags: '基本信息已保存，但标签更新失败，封面尚未处理',
            cover: '基本信息和标签已保存，但封面更新失败',
            refresh: '图书信息已保存，但无法刷新最新数据'
          }[reason.stage]
        : '保存失败';
      const cause = reason instanceof BookMetadataSaveError ? reason.cause : reason;
      feedback.error(t(stageMessage), cause instanceof Error ? cause.message : undefined);
    } finally {
      setSaving(false);
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-end justify-center bg-slate-950/45 p-0 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={t('编辑图书元数据')} onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}>
      <section className="flex max-h-[94dvh] w-full max-w-3xl flex-col overflow-hidden rounded-t-3xl border border-stone-200 bg-[#FFFEFC] shadow-2xl md:max-h-[88vh] md:rounded-3xl">
        <header className="flex items-start justify-between gap-4 border-b border-stone-100 px-5 py-4 sm:px-6">
          <div><h2 className="text-lg font-semibold text-stone-950"><I18nText>编辑图书元数据</I18nText></h2><p className="mt-1 text-sm text-stone-500"><I18nText>这些信息会应用到整本图书。</I18nText></p></div>
          <button type="button" disabled={saving} onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100 disabled:opacity-40" aria-label={t('关闭编辑')}><X size={18} /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm text-stone-600"><I18nText>标题</I18nText><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className={inputClassName} /></label>
            <label className="text-sm text-stone-600"><I18nText>作者</I18nText><input value={form.author} onChange={(event) => setForm({ ...form, author: event.target.value })} className={inputClassName} /></label>
            <label className="text-sm text-stone-600"><I18nText>系列名</I18nText><input value={form.seriesName} onChange={(event) => setForm({ ...form, seriesName: event.target.value })} className={inputClassName} /></label>
            <label className="text-sm text-stone-600"><I18nText>系列序号</I18nText><input value={form.seriesIndex} onChange={(event) => setForm({ ...form, seriesIndex: event.target.value })} inputMode="decimal" className={inputClassName} /></label>
            <div className="text-sm text-stone-600 md:col-span-2">
              <I18nText>标签</I18nText>
              <LibraryTagInput
                values={form.tags}
                onValuesChange={(tags) => setForm({ ...form, tags })}
                placeholder="输入或选择标签"
                ariaLabel="图书标签"
                className="mt-2"
                disabled={saving}
              />
            </div>
            <label className="text-sm text-stone-600 md:col-span-2"><I18nText>简介</I18nText><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={5} className={inputClassName} /></label>
          </div>
          <div className="mt-6 rounded-2xl border border-stone-200 bg-stone-50/70 p-4">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <Cover book={book} className="aspect-[2/3] w-20 shrink-0 rounded-lg shadow-sm" size="small" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-stone-800"><I18nText>封面</I18nText></div>
                <p className="mt-1 text-xs leading-5 text-stone-500">{coverChange.kind === 'replace' ? coverChange.file.name : coverChange.kind === 'remove' ? t('保存后移除当前自定义封面') : t('保留当前封面')}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <label className="inline-flex h-10 cursor-pointer items-center gap-2 rounded-xl border border-stone-200 bg-white px-3 text-sm font-medium text-stone-700 transition hover:border-orange-200 hover:text-orange-700"><ImagePlus size={16} /><I18nText>选择封面</I18nText><input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={(event) => { const file = event.target.files?.[0]; event.currentTarget.value = ''; if (!file) return; if (file.size > 12 * 1024 * 1024) { feedback.error(t('封面文件不能超过 12 MB')); return; } setCoverChange({ kind: 'replace', file }); }} /></label>
                  <button type="button" onClick={() => setCoverChange({ kind: 'remove' })} className="inline-flex h-10 items-center gap-2 rounded-xl border border-stone-200 bg-white px-3 text-sm font-medium text-red-700 transition hover:bg-red-50"><Trash2 size={16} /><I18nText>移除封面</I18nText></button>
                  {coverChange.kind !== 'keep' ? <button type="button" onClick={() => setCoverChange({ kind: 'keep' })} className={cn('h-10 rounded-xl px-3 text-sm font-medium text-stone-600 hover:bg-white')}><I18nText>撤销封面更改</I18nText></button> : null}
                </div>
              </div>
            </div>
          </div>
        </div>
        <footer className="flex shrink-0 justify-end gap-2 border-t border-stone-100 px-5 py-4 sm:px-6">
          <Button variant="secondary" disabled={saving} className="!rounded-xl" onClick={onClose}><I18nText>取消</I18nText></Button>
          <Button loading={saving} loadingText={t('保存中')} disabled={saving} icon={Save} onClick={() => void save()} className="!rounded-xl !bg-[#ff4f26] !text-white hover:!bg-[#e84420]"><I18nText>保存信息</I18nText></Button>
        </footer>
      </section>
    </div>,
    document.body
  );
}
