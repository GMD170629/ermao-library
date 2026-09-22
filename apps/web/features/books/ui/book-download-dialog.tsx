'use client';

import { BookOpen, ChevronRight, Download, File, FileArchive, FileAudio, FileImage, FileText, Folder, FolderOpen, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Button } from '../../../components/ui/button';
import type { BookView, ResourceAssetView, ResourceFormat } from '../../../types/book';
import { useI18n } from '@/i18n/provider';
import { useBookDownloadContents } from '../application/use-book-download-contents';
import { bookDownloadVolumes } from '../model/book-download';
import { downloadOriginalFiles } from './download-original-files';

function resourceIcon(format: ResourceFormat | null, mimeType = '') {
  if (mimeType.startsWith('audio/') || ['AUDIO', 'MP3', 'M4A', 'M4B', 'AUDIOBOOK_DIR'].includes(format ?? '')) return FileAudio;
  if (mimeType.startsWith('image/') || format === 'IMAGE_DIR') return FileImage;
  if (['CBZ', 'CBR', 'RAR', 'ZIP', 'COMIC'].includes(format ?? '')) return FileArchive;
  if (['EPUB', 'MOBI', 'AZW', 'AZW3', 'PRC', 'FB2'].includes(format ?? '')) return BookOpen;
  if (format === 'PDF' || format === 'TXT' || mimeType.startsWith('text/')) return FileText;
  return File;
}

type TreeProps = {
  book: BookView;
  selected: ReadonlySet<string>;
  onSelect: (assets: readonly ResourceAssetView[], checked: boolean) => void;
  onStarted: () => void;
  sizeLabel: (bytes: number) => string;
};

function DownloadFileRow({ asset, format, ...tree }: TreeProps & { asset: ResourceAssetView; format: ResourceFormat | null }) {
  const { t } = useI18n();
  const Icon = resourceIcon(asset.sourceFormat ?? format, asset.mimeType);
  return <li className="flex min-h-14 items-center gap-2 border-b border-[var(--visual-color-app-divider)] px-2 py-1 last:border-0 sm:gap-3">
    <input type="checkbox" className="h-4 w-4 shrink-0 accent-[#D94322]" aria-label={asset.title} checked={tree.selected.has(asset.id)} onChange={(event) => tree.onSelect([asset], event.target.checked)} />
    <Icon size={20} className="shrink-0 text-stone-500" aria-hidden="true" />
    <div className="flex min-w-0 flex-1 items-baseline gap-1.5 text-sm">
      <span data-i18n-skip className="truncate font-medium" title={asset.title}>{asset.title}</span>
      <span className="shrink-0 text-xs tabular-nums text-[var(--visual-color-app-text-secondary)]">({tree.sizeLabel(asset.sizeBytes)})</span>
    </div>
    <a href={asset.downloadUrl} download onClick={tree.onStarted} aria-label={t('下载 {value0}', { value0: asset.title })}
      className="inline-flex min-h-11 shrink-0 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium text-[#D94322] hover:bg-[#FFF0EA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-300">
      <Download size={16} aria-hidden="true" /><span className="hidden sm:inline">{t('下载')}</span>
    </a>
  </li>;
}

function DownloadFolder({ title, sourceNodeId, assets, format, sizeBytes, ...tree }: TreeProps & {
  title: string; sourceNodeId: string; assets?: readonly ResourceAssetView[]; format?: ResourceFormat; sizeBytes?: number | null;
}) {
  const { t, formatNumber } = useI18n();
  const [open, setOpen] = useState(false);
  const checkbox = useRef<HTMLInputElement>(null);
  const checked = !!assets?.length && assets.every((asset) => tree.selected.has(asset.id));
  const partial = !!assets?.some((asset) => tree.selected.has(asset.id)) && !checked;
  useEffect(() => { if (checkbox.current) checkbox.current.indeterminate = partial; }, [partial]);
  const Icon = open ? FolderOpen : Folder;
  const totalSize = assets ? assets.reduce((sum, asset) => sum + asset.sizeBytes, 0) : sizeBytes;
  return <li>
    <div className="flex min-h-14 items-center gap-2 border-b border-[var(--visual-color-app-divider)] px-2 py-1 sm:gap-3">
      {assets ? <input ref={checkbox} type="checkbox" className="h-4 w-4 shrink-0 accent-[#D94322]" aria-label={title} checked={checked} disabled={assets.length === 0} onChange={(event) => tree.onSelect(assets, event.target.checked)} /> : <span className="w-4 shrink-0" />}
      <button type="button" aria-expanded={open} aria-controls={`download-folder-${sourceNodeId}`} onClick={() => setOpen(!open)}
        className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-300 sm:gap-3">
        <Icon size={20} className="shrink-0 text-amber-600" aria-hidden="true" />
        <span data-i18n-skip className="truncate text-sm font-medium" title={title}>{title}</span>
        {totalSize != null ? <span className="shrink-0 text-xs tabular-nums text-stone-500">({tree.sizeLabel(totalSize)})</span> : null}
        <span className="ml-auto flex shrink-0 items-center gap-1 text-xs text-stone-500">
          {assets ? t('{count} 个文件', { count: formatNumber(assets.length) }) : null}
          <ChevronRight size={16} className={open ? 'rotate-90' : ''} aria-hidden="true" />
        </span>
      </button>
    </div>
    <div id={`download-folder-${sourceNodeId}`} hidden={!open} className="ml-3 border-l border-[var(--visual-color-app-divider)] pl-1 sm:ml-6 sm:pl-2">
      {open ? assets ? <ul>{assets.map((asset) => <DownloadFileRow key={asset.id} {...tree} asset={asset} format={format ?? null} />)}{assets.length === 0 ? <li className="px-3 py-3 text-sm text-stone-500">{t('暂无可下载文件')}</li> : null}</ul> : <DownloadTreeBranch {...tree} sourceNodeId={sourceNodeId} /> : null}
    </div>
  </li>;
}

function DownloadTreeBranch({ sourceNodeId, ...tree }: TreeProps & { sourceNodeId: string | null }) {
  const { t } = useI18n();
  const { state, retry } = useBookDownloadContents(tree.book.id, sourceNodeId);
  if (state.status === 'loading') return <p role="status" className="px-3 py-4 text-sm text-stone-500">{t('正在读取目录…')}</p>;
  if (state.status === 'error') return <div className="px-3 py-4"><p role="alert" className="text-sm">{t('读取目录失败')}</p><Button variant="secondary" className="mt-2" onClick={retry}>{t('重试')}</Button></div>;
  const volumes = bookDownloadVolumes(tree.book);
  const volumesById = new Map(volumes.map((volume) => [volume.id, volume]));
  const assetsBySourceNode = new Map(volumes.flatMap((volume) => volume.assets.map((asset) => [asset.sourceNodeId, asset] as const)));
  const rootResource = state.resourceId ? volumesById.get(state.resourceId) : undefined;
  if (rootResource) return <ul>{rootResource.assets.map((asset) => <DownloadFileRow key={asset.id} {...tree} asset={asset} format={rootResource.format} />)}</ul>;
  const entries = state.entries.flatMap((entry) => {
    const volume = entry.resourceId ? volumesById.get(entry.resourceId) : undefined;
    if (volume) {
      if (entry.kind === 'FOLDER' || volume.assets.length !== 1) return [<DownloadFolder key={entry.sourceNodeId} {...tree} sourceNodeId={entry.sourceNodeId} title={entry.title} assets={volume.assets} format={volume.format} />];
      return [<DownloadFileRow key={entry.sourceNodeId} {...tree} asset={volume.assets[0]} format={volume.format} />];
    }
    if (entry.resourceId) return [];
    if (entry.kind === 'FOLDER') return [<DownloadFolder key={entry.sourceNodeId} {...tree} sourceNodeId={entry.sourceNodeId} title={entry.title} sizeBytes={entry.sizeBytes} />];
    const asset = assetsBySourceNode.get(entry.sourceNodeId);
    return asset ? [<DownloadFileRow key={entry.sourceNodeId} {...tree} asset={asset} format={asset.sourceFormat} />] : [];
  });
  return entries.length ? <ul>{entries}</ul> : <p className="px-3 py-4 text-sm text-stone-500">{t('暂无可下载文件')}</p>;
}

export function BookDownloadDialog({ book, returnFocusTo, onClose }: {
  book: BookView;
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
}) {
  const { t, formatNumber } = useI18n();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [started, setStarted] = useState(false);
  const available = bookDownloadVolumes(book).flatMap((volume) => volume.assets);
  const files = available.filter((asset) => selected.has(asset.id));
  const allSelected = available.length > 0 && available.every((asset) => selected.has(asset.id));
  function sizeLabel(bytes: number): string {
    const exponent = bytes >= 1024 ** 3 ? 3 : bytes >= 1024 ** 2 ? 2 : bytes >= 1024 ? 1 : 0;
    return formatNumber(bytes / 1024 ** exponent, { style: 'unit', unit: ['byte', 'kilobyte', 'megabyte', 'gigabyte'][exponent], unitDisplay: 'short', maximumFractionDigits: 1 });
  }
  function select(assets: readonly ResourceAssetView[], checked: boolean) {
    setSelected((previous) => {
      const next = new Set(previous);
      for (const asset of assets) { if (checked) next.add(asset.id); else next.delete(asset.id); }
      return next;
    });
  }
  useEffect(() => { if (selectAllRef.current) selectAllRef.current.indeterminate = selected.size > 0 && !allSelected; }, [selected.size, allSelected]);
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => { dialog?.close(); if (returnFocusTo?.isConnected) returnFocusTo.focus(); };
  }, [returnFocusTo]);

  return <dialog ref={dialogRef} aria-label={t('选择下载卷册')} onCancel={(event) => { event.preventDefault(); onClose(); }}
    className="max-h-[85dvh] w-[calc(100%-2rem)] max-w-2xl overflow-hidden rounded-3xl bg-[var(--visual-color-app-surface)] p-0 text-[var(--visual-color-app-text-primary)] shadow-2xl backdrop:bg-black/45">
    <div className="flex max-h-[85dvh] flex-col">
      <header className="flex shrink-0 items-start justify-between gap-4 px-5 pb-4 pt-5 sm:px-6 sm:pt-6">
        <div className="min-w-0"><h2 className="text-lg font-semibold">{t('选择下载卷册')}</h2><p data-i18n-skip className="mt-1 truncate text-sm text-[var(--visual-color-app-text-secondary)]" title={book.title}>{book.title}</p></div>
        <button type="button" onClick={onClose} aria-label={t('关闭')} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-stone-500 hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-300"><X size={20} aria-hidden="true" /></button>
      </header>
      <div className="flex shrink-0 items-center justify-between gap-3 border-y border-[var(--visual-color-app-divider)] px-5 text-sm sm:px-6">
        <label className="flex min-h-11 cursor-pointer items-center gap-3"><input ref={selectAllRef} type="checkbox" className="h-4 w-4 accent-[#D94322]" checked={allSelected} disabled={available.length === 0} onChange={(event) => setSelected(new Set(event.target.checked ? available.map((asset) => asset.id) : []))} />{t('全选')}</label>
        <span className="text-xs tabular-nums text-[var(--visual-color-app-text-secondary)]">{t('已选择 {value0} 个文件', { value0: formatNumber(files.length) })}</span>
      </div>
      <div className="min-h-0 overflow-y-auto px-3 sm:px-4">
        <DownloadTreeBranch book={book} sourceNodeId={null} selected={selected} onSelect={select} onStarted={() => setStarted(true)} sizeLabel={sizeLabel} />
      </div>
      <footer className="shrink-0 border-t border-[var(--visual-color-app-divider)] px-5 py-4 sm:px-6">
        {started ? <div className="mb-3 text-xs text-[var(--visual-color-app-text-secondary)]"><p role="status" className="font-medium">{t('已发起下载')}</p><p className="mt-1">{t('若浏览器拦截多个下载，请允许多个文件下载，或使用行内下载按钮。')}</p></div> : null}
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>{t('关闭')}</Button><Button icon={Download} disabled={files.length === 0} onClick={() => { downloadOriginalFiles(files); setStarted(true); }}>{t('下载所选文件')}</Button></div>
      </footer>
    </div>
  </dialog>;
}
