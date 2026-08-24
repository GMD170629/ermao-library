'use client';

import { FileText, UploadCloud, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { TargetDirectoryPicker } from '../../components/directory/target-directory-picker';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useToast } from '../../components/ui/feedback';
import { saveSelectedFiles } from './application/save-selected-files';
import { I18nText } from '@/i18n/provider';
import { importFileInputAccept } from '../imports/public';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type UploadBookDialogProps = {
  open: boolean;
  onClose: () => void;
  onImported?: (message: string) => void;
  onError?: (message: string) => void;
};

function formatFileSize(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(size < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

export function UploadBookDialog({ open, onClose, onImported, onError }: UploadBookDialogProps) {
  const { t: i18nAttribute } = useAttributeI18n();
  const [saving, setSaving] = useState(false);
  const [uploadTargetPath, setUploadTargetPath] = useState('');
  const [selectedUploadFiles, setSelectedUploadFiles] = useState<File[]>([]);
  const toast = useToast();
  const selectedUploadSize = selectedUploadFiles.reduce((total, file) => total + file.size, 0);
  const visibleFiles = selectedUploadFiles.slice(0, 4);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !saving) onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose, open, saving]);

  function closeDialog() {
    if (saving) return;
    setSelectedUploadFiles([]);
    onClose();
  }

  async function saveFiles() {
    if (selectedUploadFiles.length === 0 || !uploadTargetPath) return;
    setSaving(true);
    const result = await saveSelectedFiles({
      files: selectedUploadFiles,
      targetPath: uploadTargetPath
    });
    setSaving(false);

    if (result.kind === 'saved') {
      const description = i18nAttribute('已保存 {value0} 个文件，等待书库扫描器识别', { value0: result.saved });
      toast.success(i18nAttribute('文件已保存'), description);
      onImported?.(description);
      setSelectedUploadFiles([]);
      onClose();
      return;
    }

    const message = result.kind === 'rejected'
      ? result.code === 'UPLOAD_TARGET_OUTSIDE_LIBRARY'
        ? i18nAttribute('上传目录必须位于已启用的书库中')
        : result.message
      : result.kind === 'transport-failed'
        ? i18nAttribute('网络连接失败，请检查后重试')
        : i18nAttribute('服务返回了无法识别的响应');
    toast.error(i18nAttribute('保存失败'), message);
    onError?.(message);
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-[#241F1C]/30 p-4 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label={i18nAttribute('保存图书文件')}
      onMouseDown={(event) => { if (event.target === event.currentTarget) closeDialog(); }}
    >
      <div className="w-full max-w-xl rounded-3xl border border-black/[0.08] bg-[#FFFEFC] p-6 shadow-[0_28px_80px_rgba(47,37,31,0.22)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xl font-semibold text-[#25221F]"><I18nText>保存图书文件</I18nText></div>
            <div className="mt-1.5 text-sm leading-6 text-[#817B75]"><I18nText>从已启用的书库或其子文件夹中选择保存目录。</I18nText></div>
          </div>
          <button type="button" disabled={saving} onClick={closeDialog} className="inline-flex h-10 w-10 items-center justify-center rounded-full text-[#77716B] transition hover:bg-black/[0.05] disabled:opacity-50" aria-label={i18nAttribute('关闭上传')}>
            <X size={18} />
          </button>
        </div>

        <div className="mt-6 space-y-4">
          <label className="block text-sm text-slate-600">
            <I18nText>图书文件</I18nText>
            <span className={cn('mt-2 flex min-h-14 items-center gap-3 rounded-2xl border px-4 py-3 transition', saving ? 'cursor-not-allowed border-black/[0.05] bg-black/[0.025]' : 'cursor-pointer border-black/[0.1] bg-white hover:bg-[#FBF6F2]')}>
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#FFF0EA] text-[#D9563B]"><FileText size={18} /></span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-[#393531]">{selectedUploadFiles.length > 0 ? i18nAttribute('已选择 {value0} 个文件', { value0: selectedUploadFiles.length }) : i18nAttribute('选择图书文件')}</span>
                <span className="mt-0.5 block text-xs text-[#8A847E]">{selectedUploadFiles.length > 0 ? formatFileSize(selectedUploadSize) : i18nAttribute('支持的图书文件格式')}</span>
              </span>
              <span className="shrink-0 text-xs font-medium text-[#D9563B]">{selectedUploadFiles.length > 0 ? i18nAttribute('重新选择') : i18nAttribute('浏览')}</span>
              <input
                type="file"
                multiple
                accept={importFileInputAccept}
                className="hidden"
                disabled={saving}
                onChange={(event) => {
                  setSelectedUploadFiles(Array.from(event.target.files ?? []));
                  event.target.value = '';
                }}
              />
            </span>
          </label>

          {selectedUploadFiles.length > 0 ? (
            <div className="rounded-2xl border border-black/[0.08] bg-[#FAF9F7] px-4 py-3">
              <div className="text-xs font-medium uppercase tracking-[0.12em] text-[#8A847E]"><I18nText>文件列表</I18nText></div>
              <ul className="mt-2 space-y-1.5" aria-label={i18nAttribute('已选择的文件')}>
                {visibleFiles.map((file) => <li key={`${file.name}-${file.size}-${file.lastModified}`} className="flex min-w-0 items-center justify-between gap-3 text-sm text-[#4A4540]"><span className="truncate">{file.name}</span><span className="shrink-0 text-xs text-[#8A847E]">{formatFileSize(file.size)}</span></li>)}
              </ul>
              {selectedUploadFiles.length > visibleFiles.length ? <div className="mt-2 text-xs text-[#8A847E]">{i18nAttribute('另有 {value0} 个文件', { value0: selectedUploadFiles.length - visibleFiles.length })}</div> : null}
            </div>
          ) : null}

          <TargetDirectoryPicker value={uploadTargetPath} onChange={setUploadTargetPath} memory="upload" label={i18nAttribute('保存目录')} requiredMessage={i18nAttribute('请选择保存目录')} restrictToEnabledLibraries />

          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="secondary" disabled={saving} onClick={closeDialog}><I18nText>取消</I18nText></Button>
            <Button type="button" disabled={!uploadTargetPath || selectedUploadFiles.length === 0} loading={saving} loadingText={i18nAttribute('正在保存文件')} icon={UploadCloud} onClick={() => void saveFiles()}><I18nText>保存到所选文件夹</I18nText></Button>
          </div>
        </div>
      </div>
    </div>
  );
}
