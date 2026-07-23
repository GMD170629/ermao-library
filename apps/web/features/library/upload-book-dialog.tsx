'use client';

import { ArrowRight, FileText, UploadCloud, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { TargetDirectoryPicker } from '../../components/directory/target-directory-picker';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useToast } from '../../components/ui/feedback';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type ImportResponse = {
  ok: boolean;
  data?: {
    assetCount?: number;
    results?: Array<{ message?: string }>;
  };
  error?: { message: string };
};

type UploadBookDialogProps = {
  open: boolean;
  onClose: () => void;
  onImported?: (message: string) => void;
  onError?: (message: string) => void;
};

const convertibleTextExtensions = new Set(['mobi', 'azw', 'azw3', 'prc', 'fb2', 'txt']);
const audioExtensions = new Set(['m4b', 'm4a', 'mp3']);

function fileExtension(file: File | null) {
  return file?.name.split('.').pop()?.toLowerCase() ?? '';
}

function fileFormat(file: File | null) {
  const extension = fileExtension(file);
  return extension ? extension.toUpperCase() : '未知格式';
}

function formatFileSize(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(size < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

export function UploadBookDialog({ open, onClose, onImported, onError }: UploadBookDialogProps) {
  const { t: i18nAttribute } = useAttributeI18n();
  const [uploading, setUploading] = useState(false);
  const [uploadTargetPath, setUploadTargetPath] = useState('');
  const [selectedUploadFiles, setSelectedUploadFiles] = useState<File[]>([]);
  const [uploadBookTitle, setUploadBookTitle] = useState('');
  const [uploadBookAuthor, setUploadBookAuthor] = useState('');
  const toast = useToast();
  const selectedUploadFile = selectedUploadFiles[0] ?? null;
  const selectedUploadSize = selectedUploadFiles.reduce((total, file) => total + file.size, 0);
  const selectedUploadIsAudio = selectedUploadFiles.length > 0
    && selectedUploadFiles.every((file) => audioExtensions.has(fileExtension(file)));
  const selectedAudioBundle = selectedUploadIsAudio && selectedUploadFiles.length > 1;

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !uploading) onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose, open, uploading]);

  function closeDialog() {
    if (uploading) return;
    setSelectedUploadFiles([]);
    setUploadBookTitle('');
    setUploadBookAuthor('');
    onClose();
  }

  async function uploadBook() {
    const files = selectedUploadFiles;
    const file = files[0];
    if (!file || !uploadTargetPath) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append('targetPath', uploadTargetPath);
      if (uploadBookTitle.trim()) form.append('bookTitle', uploadBookTitle.trim());
      if (uploadBookAuthor.trim()) form.append('bookAuthor', uploadBookAuthor.trim());
      files.forEach((selectedFile) => form.append('files', selectedFile));
      const response = await fetch('/api/works/import', { method: 'POST', body: form });
      const text = await response.text();
      const payload = text ? JSON.parse(text) as ImportResponse : { ok: false, error: { message: response.ok ? '导入失败' : `上传失败（HTTP ${response.status}）` } };
      if (!payload.ok) throw new Error(payload.error?.message ?? '导入失败');
      const sourceFormat = fileFormat(file);
      const successMessage = files.length > 1
        ? `${payload.data?.assetCount ?? files.length} 个音频文件已作为一本有声书加入导入队列`
        : convertibleTextExtensions.has(fileExtension(file))
          ? `${sourceFormat} 文件已加入自动转换队列`
          : (payload.data?.results?.[0]?.message ?? `${file.name} 已加入导入队列`);
      toast.success(successMessage);
      onImported?.(successMessage);
      setSelectedUploadFiles([]);
      setUploadBookTitle('');
      setUploadBookAuthor('');
      onClose();
    } catch (reason) {
      const nextError = reason instanceof SyntaxError ? '上传失败：服务器返回了无法解析的响应，请检查反向代理上传体积限制。' : reason instanceof Error ? reason.message : '导入失败';
      toast.error('导入失败', nextError);
      onError?.(nextError);
    } finally {
      setUploading(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-[#241F1C]/30 p-4 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label={i18nAttribute("导入图书")}
      onMouseDown={(event) => { if (event.target === event.currentTarget) closeDialog(); }}
    >
      <div className="w-full max-w-xl rounded-3xl border border-black/[0.08] bg-[#FFFEFC] p-6 shadow-[0_28px_80px_rgba(47,37,31,0.22)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xl font-semibold text-[#25221F]"><I18nText>导入图书</I18nText></div>
            <div className="mt-1.5 text-sm text-[#817B75]"><I18nText>可一次选择多段 MP3、M4A 或 M4B，按文件顺序合并为一本有声书。</I18nText></div>
          </div>
          <button type="button" disabled={uploading} onClick={closeDialog} className="inline-flex h-10 w-10 items-center justify-center rounded-full text-[#77716B] transition hover:bg-black/[0.05] disabled:opacity-50" aria-label={i18nAttribute("关闭上传")}>
            <X size={18} />
          </button>
        </div>
        <div className="mt-6 space-y-4">
          <label className="block text-sm text-slate-600">
            <I18nText>图书文件</I18nText><span className={cn('mt-2 flex min-h-14 items-center gap-3 rounded-2xl border px-4 py-3 transition', uploading ? 'cursor-not-allowed border-black/[0.05] bg-black/[0.025]' : 'cursor-pointer border-black/[0.1] bg-white hover:bg-[#FBF6F2]')}>
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#FFF0EA] text-[#D9563B]"><FileText size={18} /></span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-[#393531]">{selectedAudioBundle ? i18nAttribute("已选择 {value0} 个音频文件", { value0: selectedUploadFiles.length }) : selectedUploadFile?.name ?? i18nAttribute("选择图书文件")}</span>
                <span className="mt-0.5 block text-xs text-[#8A847E]">{selectedUploadFile ? `${selectedAudioBundle ? '有声书音轨组' : fileFormat(selectedUploadFile)} · ${formatFileSize(selectedUploadSize)}` : i18nAttribute("电子书、漫画与 M4B、M4A、MP3 有声书")}</span>
              </span>
              <span className="shrink-0 text-xs font-medium text-[#D9563B]">{selectedUploadFile ? i18nAttribute("重新选择") : i18nAttribute("浏览")}</span>
              <input
                type="file"
                multiple
                accept=".epub,.mobi,.azw,.azw3,.prc,.fb2,.txt,.cbz,.zip,.pdf,.m4b,.m4a,.mp3,application/epub+zip,application/zip,application/pdf,text/plain,audio/mp4,audio/mpeg"
                className="hidden"
                disabled={uploading}
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  if (files.length > 1 && files.some((candidate) => !audioExtensions.has(fileExtension(candidate)))) {
                    toast.error('无法组合这些文件', '批量导入仅支持 MP3、M4A 与 M4B；其他格式请逐本导入。');
                    setSelectedUploadFiles([]);
                  } else {
                    setSelectedUploadFiles(files);
                  }
                  event.target.value = '';
                }}
              />
            </span>
          </label>
          {selectedUploadFiles.length === 1 && selectedUploadFile && convertibleTextExtensions.has(fileExtension(selectedUploadFile)) ? (
            <div className="rounded-2xl border border-[#F1DED6] bg-[#FFF9F6] px-4 py-3">
              <div className="text-xs font-medium uppercase tracking-[0.12em] text-[#A56B5A]"><I18nText>处理方式</I18nText></div>
              <div className="mt-2 flex items-center gap-2 text-sm font-semibold text-[#3A3531]">
                <span>{fileFormat(selectedUploadFile)}</span><ArrowRight size={15} className="text-[#C58C7A]" /><span>EPUB</span><span className="ml-auto rounded-full bg-[#FBE1D8] px-2.5 py-1 text-xs text-[#B44E35]"><I18nText>自动转换</I18nText></span>
              </div>
              <div className="mt-2 text-xs leading-5 text-[#817B75]"><I18nText>系统会自动识别章节和书内资源；源文件会保留，转换失败时可在导入任务中查看原因。</I18nText></div>
            </div>
          ) : null}
          {selectedUploadIsAudio ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-sm text-slate-600"><I18nText>有声书名称 </I18nText><span className="text-xs text-[#9A948E]"><I18nText>（可选）</I18nText></span><input value={uploadBookTitle} onChange={(event) => setUploadBookTitle(event.target.value)} placeholder={i18nAttribute("留空时读取专辑标签")} className="mt-2 h-11 w-full rounded-2xl border border-black/[0.1] bg-white px-4 text-[#393531] outline-none transition placeholder:text-[#AAA49E] focus:border-[#E8A18D] focus:ring-2 focus:ring-[#F9DED4]" /></label>
              <label className="block text-sm text-slate-600"><I18nText>作者 </I18nText><span className="text-xs text-[#9A948E]"><I18nText>（可选）</I18nText></span><input value={uploadBookAuthor} onChange={(event) => setUploadBookAuthor(event.target.value)} placeholder={i18nAttribute("留空时读取作者标签")} className="mt-2 h-11 w-full rounded-2xl border border-black/[0.1] bg-white px-4 text-[#393531] outline-none transition placeholder:text-[#AAA49E] focus:border-[#E8A18D] focus:ring-2 focus:ring-[#F9DED4]" /></label>
              <p className="text-xs leading-5 text-[#817B75] sm:col-span-2"><I18nText>填写后会优先用于作品识别与现有电子书、漫画版本合并；留空则按音频标签和文件名自动识别。</I18nText></p>
            </div>
          ) : null}
          <TargetDirectoryPicker value={uploadTargetPath} onChange={setUploadTargetPath} memory="upload" label={i18nAttribute("保存目录")} requiredMessage={i18nAttribute("请选择保存目录")} processingMode="queue" />
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="secondary" disabled={uploading} onClick={closeDialog}><I18nText>取消</I18nText></Button>
            <Button type="button" disabled={!uploadTargetPath || selectedUploadFiles.length === 0} loading={uploading} loadingText={i18nAttribute("正在加入队列")} icon={UploadCloud} onClick={() => void uploadBook()}><I18nText>开始导入</I18nText></Button>
          </div>
        </div>
      </div>
    </div>
  );
}
