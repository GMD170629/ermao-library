'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { useToast } from '../../../components/ui/feedback';
import { useI18n } from '@/i18n/provider';
import { updateBulkBookShelfMembership } from '../../library/public';
import { fetchShelves, type ShelfView } from '../../shelves/public';

export function BookShelfDialog({ book, returnFocusTo, onClose }: {
  book: Readonly<{ id: string; title: string }>;
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const feedback = useToast();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const alive = useRef(false);
  const savingRef = useRef(false);
  const [shelves, setShelves] = useState<ShelfView[]>([]);
  const [shelfId, setShelfId] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    alive.current = true;
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => {
      alive.current = false;
      dialog?.close();
      if (returnFocusTo?.isConnected) returnFocusTo.focus();
    };
  }, [returnFocusTo]);

  useEffect(() => {
    const controller = new AbortController();
    fetchShelves(controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setShelves(items.filter((shelf) => shelf.kind === 'STATIC'));
      setLoading(false);
    }).catch(() => {
      if (controller.signal.aborted) return;
      setLoadFailed(true);
      setLoading(false);
    });
    return () => controller.abort();
  }, [attempt]);

  async function save() {
    if (savingRef.current || !shelves.some((shelf) => shelf.id === shelfId)) return;
    savingRef.current = true;
    setSaving(true);
    setSaveFailed(false);
    try {
      await updateBulkBookShelfMembership({ ids: [book.id], shelfId, membership: 'ADD' });
      if (!alive.current) return;
      feedback.success(t('图书已加入所选书架'));
      onClose();
    } catch {
      if (alive.current) setSaveFailed(true);
    } finally {
      savingRef.current = false;
      if (alive.current) setSaving(false);
    }
  }

  return <dialog ref={dialogRef} aria-label={t('加入书架')} onCancel={(event) => {
    event.preventDefault();
    if (!savingRef.current) onClose();
  }} className="w-[calc(100%-2rem)] max-w-md rounded-3xl bg-[var(--visual-color-app-surface)] p-6 text-[var(--visual-color-app-text-primary)] shadow-2xl backdrop:bg-black/45">
    <h2 className="text-lg font-semibold">{t('加入书架')}</h2>
    <p data-i18n-skip className="mt-2 break-words text-sm">{book.title}</p>
    <p className="mt-2 text-sm text-[var(--visual-color-app-text-secondary)]">{t('保留已有书架归属')}</p>
    {loading ? <p role="status" className="mt-5">{t('正在读取书架…')}</p> : loadFailed ? <div className="mt-5">
      <p role="alert">{t('读取书架失败')}</p>
      <Button variant="secondary" className="mt-3" onClick={() => { setLoadFailed(false); setLoading(true); setAttempt((value) => value + 1); }}>{t('重试')}</Button>
    </div> : shelves.length === 0 ? <p role="status" className="mt-5">{t('暂无普通书架')}</p> : <label className="mt-5 block text-sm">
      {t('目标书架')}
      <select value={shelfId} onChange={(event) => setShelfId(event.target.value)} disabled={saving} className="mt-2 w-full rounded-xl border border-[var(--visual-color-app-divider)] bg-[var(--visual-color-app-surface)] p-3">
        <option value="">{t('请选择普通书架')}</option>
        {shelves.map((shelf) => <option key={shelf.id} value={shelf.id} data-i18n-skip>{shelf.name}</option>)}
      </select>
    </label>}
    {saveFailed ? <p role="alert" className="mt-3">{t('保存书架失败')} {t('请稍后重试')}</p> : null}
    <div className="mt-6 flex justify-end gap-2">
      <Button variant="secondary" disabled={saving} onClick={onClose}>{t('取消')}</Button>
      <Button loading={saving} disabled={loading || loadFailed || !shelfId} onClick={() => void save()}>{t('加入书架')}</Button>
    </div>
  </dialog>;
}
