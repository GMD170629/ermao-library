'use client';

import { BookCheck, BookX, Edit3, RefreshCw, ScanSearch, Sparkles, Trash2, type LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { ContextActionMenu, type ContextMenuPosition } from '../../../components/ui/context-action-menu';
import { useToast } from '../../../components/ui/feedback';
import type { BookView } from '../../../types/book';
import { useI18n } from '@/i18n/provider';
import {
  continueSourceNode,
  deleteBookSources,
  fetchBook,
  regenerateBookImage,
  updateBookReadingStatus
} from '../api/client';
import {
  bookActionIds,
  nextBookReadingStatus,
  type BookActionId,
  type BookReadingStatus
} from '../model/book-action-menu';
import { MetadataLookupModal } from '../metadata-lookup-modal';
import { BookMetadataEditor } from './book-metadata-editor';

export type BookActionTarget = Readonly<{
  id: string;
  title: string;
  status: BookReadingStatus;
}>;

export type BookActionMenuRequest = Readonly<{
  target: BookActionTarget;
  position: ContextMenuPosition;
  anchor: HTMLElement | null;
  book?: BookView;
}>;

const actionDetails: Record<Exclude<BookActionId, 'reading-status'>, { label: string; icon: LucideIcon; destructive?: boolean }> = {
  edit: { label: '编辑', icon: Edit3 },
  'regenerate-image': { label: '重新生成图片', icon: RefreshCw },
  recognize: { label: '识别', icon: Sparkles },
  rescan: { label: '重新扫描文件', icon: ScanSearch },
  delete: { label: '删除', icon: Trash2, destructive: true }
};

export function BookActionController({
  request,
  canManage,
  onRequestClose,
  onChanged,
  onDeleted
}: {
  request: BookActionMenuRequest | null;
  canManage: boolean;
  onRequestClose: () => void;
  onChanged: (book?: BookView) => void | Promise<void>;
  onDeleted: (bookId: string) => void | Promise<void>;
}) {
  const { t } = useI18n();
  const feedback = useToast();
  const [busy, setBusy] = useState<BookActionId | null>(null);
  const [editorBook, setEditorBook] = useState<BookView | null>(null);
  const [recognitionBook, setRecognitionBook] = useState<BookView | null>(null);

  async function resolveBook(currentRequest: BookActionMenuRequest): Promise<BookView> {
    return currentRequest.book?.id === currentRequest.target.id
      ? currentRequest.book
      : fetchBook(currentRequest.target.id);
  }

  async function invoke(action: BookActionId) {
    const currentRequest = request;
    if (!currentRequest || (action !== 'reading-status' && !canManage)) return;
    onRequestClose();

    if (action === 'delete') {
      const confirmed = await feedback.confirm({
        title: '删除图书和源文件',
        description: t('将永久删除《{value0}》及其源文件、资源和阅读记录，此操作无法恢复。', { value0: currentRequest.target.title }),
        confirmLabel: '删除',
        tone: 'danger',
        confirmationText: currentRequest.target.title
      });
      if (!confirmed) return;
    }

    setBusy(action);
    try {
      if (action === 'edit') {
        setEditorBook(await resolveBook(currentRequest));
        return;
      }
      if (action === 'recognize') {
        setRecognitionBook(await resolveBook(currentRequest));
        return;
      }
      if (action === 'regenerate-image') {
        await regenerateBookImage(currentRequest.target.id);
        feedback.success(t('已开始重新生成图书图片'));
        await onChanged();
        return;
      }
      if (action === 'reading-status') {
        const nextStatus = nextBookReadingStatus(currentRequest.target.status);
        await updateBookReadingStatus(currentRequest.target.id, nextStatus);
        feedback.success(t(nextStatus === 'FINISHED' ? '已标记为已读' : '已标记为未读'));
        await onChanged();
        return;
      }
      if (action === 'rescan') {
        const targetBook = await resolveBook(currentRequest);
        await continueSourceNode(targetBook.sourceNodeId);
        feedback.success(t('已加入重新扫描队列'));
        await onChanged();
        return;
      }
      await deleteBookSources(currentRequest.target.id);
      feedback.success(t('图书及源文件已删除'));
      await onDeleted(currentRequest.target.id);
    } catch (reason) {
      feedback.error(t('图书操作失败'), reason instanceof Error ? reason.message : t('请稍后重试'));
    } finally {
      setBusy(null);
    }
  }

  const readingTarget = request ? nextBookReadingStatus(request.target.status) : 'FINISHED';
  const menuItems = request ? bookActionIds(canManage).map((action) => {
    if (action === 'reading-status') {
      return {
        action,
        label: t(readingTarget === 'FINISHED' ? '设为已读' : '设为未读'),
        icon: readingTarget === 'FINISHED' ? BookCheck : BookX,
        disabled: busy !== null
      };
    }
    const details = actionDetails[action];
    return {
      action,
      label: t(details.label),
      icon: details.icon,
      destructive: details.destructive,
      separatorBefore: action === 'delete',
      disabled: busy !== null
    };
  }) : [];

  return <>
    {request ? <ContextActionMenu<BookActionId>
      position={request.position}
      ariaLabel={t('管理图书')}
      title={request.target.title}
      items={menuItems}
      returnFocusTo={request.anchor}
      onClose={onRequestClose}
      onSelect={(action) => { void invoke(action); }}
    /> : null}
    {editorBook ? <BookMetadataEditor
      book={editorBook}
      open
      onClose={() => setEditorBook(null)}
      onSaved={(nextBook) => { setEditorBook(nextBook); void onChanged(nextBook); }}
    /> : null}
    {recognitionBook ? <MetadataLookupModal
      book={recognitionBook}
      fixedScope="book"
      open
      onClose={() => setRecognitionBook(null)}
      onApplied={async () => {
        const nextBook = await fetchBook(recognitionBook.id);
        setRecognitionBook(nextBook);
        await onChanged(nextBook);
      }}
    /> : null}
  </>;
}
