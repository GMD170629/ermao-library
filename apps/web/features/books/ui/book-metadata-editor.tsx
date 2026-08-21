'use client';

import { Save, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { useToast } from '../../../components/ui/feedback';
import type { BookView } from '../../../types/book';
import { I18nText, useI18n } from '@/i18n/provider';
import { updateBookMetadata } from '../api/client';

type BookForm = Readonly<{
  title: string;
  author: string;
  description: string;
  seriesName: string;
  seriesIndex: string;
  tags: string;
}>;

function formForBook(book: BookView): BookForm {
  return {
    title: book.title,
    author: book.author,
    description: book.description,
    seriesName: book.seriesName ?? '',
    seriesIndex: book.seriesIndex === null ? '' : String(book.seriesIndex),
    tags: book.tags.join(', ')
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
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setForm(formForBook(book));
  }, [open, book]);

  if (!open) return null;

  async function save() {
    const title = form.title.trim();
    if (!title) {
      feedback.error(t('标题不能为空'));
      return;
    }
    setSaving(true);
    try {
      const nextBook = await updateBookMetadata(book.id, {
        title,
        author: form.author.trim(),
        description: form.description.trim(),
        seriesName: form.seriesName.trim() || null,
        seriesIndex: form.seriesIndex.trim() ? Number(form.seriesIndex) : null,
        tags: form.tags.split(/[,，\n]/).map((tag) => tag.trim()).filter(Boolean)
      });
      onSaved(nextBook);
      feedback.success(t('图书信息已保存'));
    } catch (reason) {
      feedback.error(reason instanceof Error ? reason.message : t('保存失败'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section id="book-metadata-editor" className="mt-5 rounded-[22px] border border-stone-200 bg-white p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-stone-950"><I18nText>编辑元数据</I18nText></h2>
          <p className="mt-1 text-sm text-stone-500"><I18nText>图书信息会应用到这本图书的全部资源。</I18nText></p>
        </div>
        <button type="button" onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100" aria-label={t('关闭编辑')}><X size={18} /></button>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <label className="text-sm text-stone-600"><I18nText>标题</I18nText><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className={inputClassName} /></label>
        <label className="text-sm text-stone-600"><I18nText>作者</I18nText><input value={form.author} onChange={(event) => setForm({ ...form, author: event.target.value })} className={inputClassName} /></label>
        <label className="text-sm text-stone-600"><I18nText>系列名</I18nText><input value={form.seriesName} onChange={(event) => setForm({ ...form, seriesName: event.target.value })} className={inputClassName} /></label>
        <label className="text-sm text-stone-600"><I18nText>系列序号</I18nText><input value={form.seriesIndex} onChange={(event) => setForm({ ...form, seriesIndex: event.target.value })} inputMode="decimal" className={inputClassName} /></label>
        <label className="text-sm text-stone-600 md:col-span-2"><I18nText>标签</I18nText><input value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} placeholder={t('标签，用逗号分隔')} className={inputClassName} /></label>
        <label className="text-sm text-stone-600 md:col-span-2"><I18nText>简介</I18nText><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={5} className={inputClassName} /></label>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" className="!rounded-xl" onClick={onClose}><I18nText>取消</I18nText></Button>
        <Button loading={saving} loadingText={t('保存中')} disabled={saving} icon={Save} onClick={() => void save()} className="!rounded-xl !bg-[#ff4f26] !text-white hover:!bg-[#e84420]"><I18nText>保存信息</I18nText></Button>
      </div>
    </section>
  );
}
