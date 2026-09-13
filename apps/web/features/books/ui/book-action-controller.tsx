'use client';

import { BookCheck, BookX, Edit3, RefreshCw, ScanSearch, Send, Sparkles, Trash2, type LucideIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  ContextActionMenu,
  type ContextActionMenuHorizontalAlign,
  type ContextMenuPosition
} from '../../../components/ui/context-action-menu';
import { useToast } from '../../../components/ui/feedback';
import type { BookView } from '../../../types/book';
import { useI18n } from '@/i18n/provider';
import {
  continueSourceImport,
  waitForImportTask
} from '@/features/import-tasks/public';
import {
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
import { KindleSendModal } from '../kindle-send-modal';
import { kindleSendOptions } from '../model/kindle-send';

export type BookActionTarget = Readonly<{
  id: string;
  title: string;
  status: BookReadingStatus;
}>;

export type BookActionMenuRequest = Readonly<{
  target: BookActionTarget;
  position: ContextMenuPosition;
  horizontalAlign?: ContextActionMenuHorizontalAlign;
  anchor: HTMLElement | null;
  book?: BookView;
}>;

function skippedCoverDetails(skipped: ReadonlyArray<{ bookId: string; reason: string }>): string | undefined {
  if (skipped.length === 0) return undefined;
  return skipped.map((item) => `${item.bookId}: ${item.reason}`).join('；');
}

const actionDetails: Record<Exclude<BookActionId, 'reading-status'>, { label: string; icon: LucideIcon; destructive?: boolean }> = {
  edit: { label: '编辑', icon: Edit3 },
  'regenerate-image': { label: '重新生成图片', icon: RefreshCw },
  recognize: { label: '识别', icon: Sparkles },
  rescan: { label: '重新扫描文件', icon: ScanSearch },
  kindle: { label: '发送到 Kindle', icon: Send },
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
  const [kindleBook, setKindleBook] = useState<BookView | null>(null);
  const [menuBook, setMenuBook] = useState<BookView | null>(null);
  const resolvedMenuBook = request?.book ?? (menuBook?.id === request?.target.id ? menuBook : null);

  useEffect(() => {
    if (!request || request.book) return;
    const controller = new AbortController();
    fetchBook(request.target.id, controller.signal).then((book) => {
      if (!controller.signal.aborted) setMenuBook(book);
    }).catch(() => {
      if (!controller.signal.aborted) setMenuBook(null);
    });
    return () => controller.abort();
  }, [request]);

  async function resolveBook(currentRequest: BookActionMenuRequest): Promise<BookView> {
    return currentRequest.book?.id === currentRequest.target.id
      ? currentRequest.book
      : menuBook?.id === currentRequest.target.id ? menuBook : fetchBook(currentRequest.target.id);
  }

  async function invoke(action: BookActionId) {
    const currentRequest = request;
    if (!currentRequest || busy || (!['reading-status', 'kindle'].includes(action) && !canManage)) return;
    onRequestClose();

    if (action === 'delete') {
      const confirmed = await feedback.confirm({
        title: '删除图书和源文件',
        description: t('将永久删除《{value0}》及其源文件、资源和阅读记录，此操作无法恢复。', { value0: currentRequest.target.title }),
        confirmLabel: '删除',
        tone: 'danger'
      });
      if (!confirmed) return;
    }

    setBusy(action);
    try {
      if (action === 'kindle') {
        setKindleBook(await resolveBook(currentRequest));
        return;
      }
      if (action === 'edit') {
        setEditorBook(await resolveBook(currentRequest));
        return;
      }
      if (action === 'recognize') {
        setRecognitionBook(await resolveBook(currentRequest));
        return;
      }
      if (action === 'regenerate-image') {
        const result = await regenerateBookImage(currentRequest.target.id);
        const skipped = skippedCoverDetails(result.skipped);
        if (result.updated <= 0) {
          feedback.error(t('封面更新失败，请稍后重试'), skipped);
          return;
        }
        if (result.skipped.length > 0) {
          feedback.info(
            t('已处理 {value0} 本图书的封面{value1}', {
              value0: result.updated,
              value1: t('，跳过 {value0} 本', { value0: result.skipped.length })
            }),
            skipped
          );
        } else {
          feedback.success(t('封面已重新生成'));
        }
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
        const requestResult = await continueSourceImport(targetBook.sourceNodeId);
        feedback.success(t('已加入重新扫描队列'));
        if (requestResult.taskId) {
          const task = await waitForImportTask(requestResult.taskId);
          if (task?.state === 'FAILED') {
            throw new Error(task.errorSummary ?? t('重新扫描失败'));
          }
        }
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
  const menuItems = request ? bookActionIds(canManage, !!resolvedMenuBook && kindleSendOptions(resolvedMenuBook).length > 0).map((action) => {
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
    {kindleBook ? <KindleSendModal book={kindleBook} open preferredResourceId={null} onClose={() => setKindleBook(null)} /> : null}
    {request ? <ContextActionMenu<BookActionId>
      position={request.position}
      ariaLabel={t('管理图书')}
      title={request.target.title}
      items={menuItems}
      width="compact"
      horizontalAlign={request.horizontalAlign}
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
