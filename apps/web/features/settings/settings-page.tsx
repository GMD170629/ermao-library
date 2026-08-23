'use client';

import { CheckCircle2, ChevronDown, ChevronRight, Database, Download, FolderOpen, RotateCcw, Save, Settings2, SlidersHorizontal, Trash2 } from 'lucide-react';
import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useConfirm, useToast } from '../../components/ui/feedback';
import { useI18n } from '../../i18n/provider';
import { PageTitle } from '../../components/ui/page-title';
import { Select } from '../../components/ui/select';
import { withBasePath } from '../../lib/base-path';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { DirectoryPathPicker as SharedDirectoryPathPicker } from './ui/directory-path-picker';

type OrganizationMode = 'FLAT' | 'VOLUMES';

type Library = {
  id: string;
  name: string;
  rootPath: string;
  enabled: boolean;
  ignorePatterns?: string | null;
  ignoreHidden: boolean;
  minFileSizeBytes: number;
  organizationMode: OrganizationMode;
  description?: string | null;
};

type LibrariesPayload = {
  libraries: Library[];
  lastUploadTargetPath?: string | null;
  lastDownloadTargetPath?: string | null;
};

const ORGANIZATION_MODE_OPTIONS: Array<{
  value: OrganizationMode;
  label: string;
  description: string;
}> = [
  { value: 'FLAT', label: '平铺', description: '平铺：根目录文件各自作为独立图书' },
  { value: 'VOLUMES', label: '按目录归组', description: '按目录归组：图书 / 可读资源 / 资产' }
];

function organizationModeLabel(mode: OrganizationMode): string {
  return ORGANIZATION_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode;
}

function organizationModeDescription(mode: OrganizationMode): string {
  return ORGANIZATION_MODE_OPTIONS.find((option) => option.value === mode)?.description ?? '';
}

type BackupItem = {
  id: string;
  kind: 'manual' | 'automatic' | 'unknown';
  filename: string;
  sizeBytes: number;
  createdAt: string;
  counts?: {
    books: number;
    readingProgresses: number;
    libraries: number;
  };
};

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function SettingsPage({ embedded = false, initialSection }: { embedded?: boolean; initialSection?: string }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const { locale } = useI18n();
  const groups = ['书库', '备份与恢复'];
  const [active, setActive] = useState(initialSection ?? '书库');
  const [folders, setFolders] = useState<Library[]>([]);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [name, setName] = useState('我的书库');
  const [rootPath, setRootPath] = useState('');
  const [ignorePatterns, setIgnorePatterns] = useState('');
  const [ignoreHidden, setIgnoreHidden] = useState(true);
  const [minFileSizeKb, setMinFileSizeKb] = useState('10');
  const [organizationMode, setOrganizationMode] = useState<OrganizationMode>('FLAT');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [backupBusy, setBackupBusy] = useState('');
  const [pathBusy, setPathBusy] = useState('');
  const [ruleBusy, setRuleBusy] = useState('');
  const [showCreateFolder, setShowCreateFolder] = useState(false);
  const [showCreateRules, setShowCreateRules] = useState(true);
  const [expandedRules, setExpandedRules] = useState<Record<string, boolean>>({});
  const confirm = useConfirm();
  const toast = useToast();

  const loadPaths = useCallback(async () => {
    const response = await fetch('/api/libraries');
    const payload = (await response.json()) as { ok: boolean; data?: LibrariesPayload; error?: { message: string } };
    if (payload.ok) {
      setFolders(payload.data?.libraries ?? []);
    } else {
      setError(payload.error?.message ?? '读取书库失败');
    }
  }, []);

  const loadBackups = useCallback(async () => {
    const response = await fetch('/api/backups');
    const payload = (await response.json()) as { ok: boolean; data?: { backups: BackupItem[] }; error?: { message: string } };
    if (payload.ok) setBackups(payload.data?.backups ?? []);
    else setError(payload.error?.message ?? '读取备份列表失败');
  }, []);

  useEffect(() => {
    if (active === '监控规则') setActive('书库');
  }, [active]);

  useEffect(() => {
    if (initialSection) setActive(initialSection);
  }, [initialSection]);

  useEffect(() => {
    if (active === '监控规则') return;
    setError('');
    if (active === '书库') {
      void loadPaths();
    } else if (active === '备份与恢复') {
      void loadBackups();
    }
  }, [active, loadBackups, loadPaths]);

  async function savePath(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setMessage('');
    setPathBusy('create');
    const response = await fetch('/api/libraries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, rootPath, organizationMode, enabled: true, ignorePatterns, ignoreHidden, minFileSizeBytes: Math.max(0, Math.round(Number(minFileSizeKb || 0) * 1024)) })
    });
    const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
    if (!payload.ok) {
      const nextError = payload.error?.message ?? '保存失败';
      setError(nextError);
      toast.error('保存失败', nextError);
      setPathBusy('');
      return;
    }
    setMessage('书库已保存');
    toast.success('书库已保存');
    await loadPaths();
    setShowCreateFolder(false);
    setPathBusy('');
  }

  function toggleCreateFolderForm() {
    const nextVisible = !showCreateFolder;
    setShowCreateFolder(nextVisible);
    if (nextVisible) setShowCreateRules(true);
  }

  async function togglePath(path: Library) {
    setPathBusy(`toggle:${path.id}`);
    await fetch(`/api/libraries/${path.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !path.enabled })
    });
    await loadPaths();
    toast.success(path.enabled ? '书库已停用' : '书库已启用');
    setPathBusy('');
  }

  async function deletePath(path: Library) {
    const confirmed = await confirm({
      title: '删除书库',
      description: `删除书库“${path.name}”？不会删除原始读物文件。`,
      confirmLabel: '删除',
      tone: 'danger'
    });
    if (!confirmed) return;
    setPathBusy(`delete:${path.id}`);
    await fetch(`/api/libraries/${path.id}`, { method: 'DELETE' });
    await loadPaths();
    toast.success('书库已删除');
    setPathBusy('');
  }

  async function saveFolderSettings(path: Library, updates: Pick<Library, 'name' | 'rootPath' | 'ignorePatterns' | 'ignoreHidden' | 'minFileSizeBytes' | 'organizationMode'>) {
    setError('');
    setMessage('');
    setRuleBusy(path.id);
    const response = await fetch(`/api/libraries/${path.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
    if (!payload.ok) {
      const nextError = payload.error?.message ?? '保存书库设置失败';
      setError(nextError);
      toast.error('保存书库设置失败', nextError);
      setRuleBusy('');
      return;
    }
    setMessage('书库设置已保存');
    toast.success('书库设置已保存');
    await loadPaths();
    setRuleBusy('');
  }

  async function createBackup() {
    setError('');
    setMessage('');
    setBackupBusy('create');
    const response = await fetch('/api/backups', { method: 'POST' });
    const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
    setBackupBusy('');
    if (!payload.ok) {
      const nextError = payload.error?.message ?? '创建备份失败';
      setError(nextError);
      toast.error('创建备份失败', nextError);
      return;
    }
    setMessage('备份已创建');
    toast.success('备份已创建');
    await loadBackups();
  }

  function downloadBackup(backup: BackupItem) {
    window.location.href = withBasePath(`/api/backups/${backup.id}/download`);
  }

  async function restoreBackup(backup: BackupItem) {
    const first = await confirm({
      title: '恢复备份',
      description: '恢复备份会覆盖当前读物元数据、标签、阅读进度和书库配置，但不会删除原始读物文件。是否继续？',
      confirmLabel: '继续恢复',
      tone: 'danger'
    });
    if (!first) return;
    const confirmText = window.prompt(i18nAttribute('二次确认：请输入 RESTORE 恢复备份 {value0}', { value0: backup.filename }));
    if (confirmText !== 'RESTORE') {
      setError('恢复已取消：确认文本不匹配');
      toast.info('恢复已取消', '确认文本不匹配');
      return;
    }
    setError('');
    setMessage('');
    setBackupBusy(`restore:${backup.id}`);
    const response = await fetch(`/api/backups/${backup.id}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: true, confirmText })
    });
    const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
    setBackupBusy('');
    if (!payload.ok) {
      const nextError = payload.error?.message ?? '恢复备份失败';
      setError(nextError);
      toast.error('恢复备份失败', nextError);
      return;
    }
    setMessage('备份已恢复，原始读物文件未被删除');
    toast.success('备份已恢复', '原始读物文件未被删除');
    await Promise.all([loadPaths(), loadBackups()]);
  }

  async function deleteBackup(backup: BackupItem) {
    const confirmed = await confirm({
      title: '删除备份',
      description: `删除备份 ${backup.filename}？`,
      confirmLabel: '删除',
      tone: 'danger'
    });
    if (!confirmed) return;
    setError('');
    setMessage('');
    setBackupBusy(`delete:${backup.id}`);
    const response = await fetch(`/api/backups/${backup.id}`, { method: 'DELETE' });
    const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
    setBackupBusy('');
    if (!payload.ok) {
      const nextError = payload.error?.message ?? '删除备份失败';
      setError(nextError);
      toast.error('删除备份失败', nextError);
      return;
    }
    setMessage('备份已删除');
    toast.success('备份已删除');
    await loadBackups();
  }

  return (
    <div className={embedded ? '' : 'space-y-6'}>
      {!embedded ? <PageTitle
        title={i18nAttribute("系统设置")}
        desc={i18nAttribute("配置监控导入、备份、智能整理和外部来源。")}
      /> : null}
      <div className={embedded ? 'block' : 'grid grid-cols-1 gap-6 lg:grid-cols-12'}>
        {!embedded ? <div className="rounded-[28px] border border-slate-200 bg-white p-4 shadow-sm lg:col-span-3">
          {groups.map((group) => (
            <button
              key={group}
              onClick={() => setActive(group)}
              className={cn('mb-1 flex w-full items-center justify-between rounded-2xl px-4 py-3 text-sm', active === group ? 'bg-[#fff0ea] text-[#d94724]' : 'text-slate-600 hover:bg-slate-50')}
            >
              <span>{group}</span>
              <ChevronRight size={16} />
            </button>
          ))}
        </div> : null}
        <div className={embedded ? 'min-w-0' : 'rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm lg:col-span-9'}>
          {!embedded ? <h1 className="text-xl font-semibold">{active}</h1> : null}
          {active === '书库' ? (
            <div className="mt-6 space-y-5">
              <div className="flex justify-end">
                <Button type="button" variant="secondary" icon={FolderOpen} onClick={toggleCreateFolderForm}>
                  {showCreateFolder ? i18nAttribute("收起添加表单") : i18nAttribute("新增书库")}
                </Button>
              </div>
              {showCreateFolder ? <form onSubmit={savePath} className="grid grid-cols-1 gap-3 rounded-[20px] border border-slate-200 bg-slate-50 p-4 md:grid-cols-12 md:items-end">
                <label className="md:col-span-3">
                  <span className="text-sm font-medium text-slate-700"><I18nText>名称</I18nText></span>
                  <input value={name} onChange={(event) => setName(event.target.value)} className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 px-3 text-sm outline-none focus:border-[#F19B84] focus:ring-2 focus:ring-[#FCE5DE]" />
                </label>
                <div className="md:col-span-7">
                  <span className="text-sm font-medium text-slate-700"><I18nText>书库路径</I18nText></span>
                  <SharedDirectoryPathPicker value={rootPath} onChange={setRootPath} compact />
                </div>
                <div className="md:col-span-2">
                  <Button className="h-10 w-full" icon={FolderOpen} loading={pathBusy === 'create'} loadingText={i18nAttribute("保存中")}><I18nText>保存</I18nText></Button>
                </div>
                <label className="md:col-span-4">
                  <span className="text-sm font-medium text-slate-700"><I18nText>组织方式</I18nText></span>
                  <Select value={organizationMode} onChange={(value) => setOrganizationMode(value as OrganizationMode)} ariaLabel="组织方式" className="mt-1.5 w-full" size="sm" options={ORGANIZATION_MODE_OPTIONS.map((option) => ({ value: option.value, label: option.label }))} />
                </label>
                <div className="self-end text-xs leading-5 text-slate-500 md:col-span-8">{i18nAttribute(organizationModeDescription(organizationMode))}</div>
                <div className="text-xs leading-5 text-slate-500 md:col-span-12"><I18nText>图书会进入书库；每位用户可按来源文件夹创建自己的智能书架。</I18nText></div>
                <button
                  type="button"
                  aria-expanded={showCreateRules}
                  onClick={() => setShowCreateRules((current) => !current)}
                  className="flex min-h-9 items-center gap-2 text-left text-sm font-medium text-slate-600 hover:text-[#D94724] md:col-span-12"
                >
                  <SlidersHorizontal size={15} />
                  <I18nText>扫描规则</I18nText><ChevronDown size={15} className={cn('transition-transform', showCreateRules && 'rotate-180')} />
                  <span className="font-normal text-slate-400"><I18nText>默认忽略隐藏文件，小于 10 KB 跳过</I18nText></span>
                </button>
                {showCreateRules ? (
                  <div className="grid gap-3 border-t border-slate-200 pt-3 md:col-span-12 md:grid-cols-12">
                    <label className="md:col-span-7">
                      <span className="text-sm font-medium text-slate-700"><I18nText>自定义忽略规则</I18nText></span>
                      <textarea
                        value={ignorePatterns}
                        onChange={(event) => setIgnorePatterns(event.target.value)}
                        rows={2}
                        placeholder={i18nAttribute("每行一条 glob 规则，例如 **/temp/**")}
                        className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2 font-mono text-sm outline-none focus:border-[#F19B84] focus:ring-2 focus:ring-[#FCE5DE]"
                      />
                    </label>
                    <label className="md:col-span-3">
                      <span className="text-sm font-medium text-slate-700"><I18nText>最小文件大小 KB</I18nText></span>
                      <input type="number" min={0} value={minFileSizeKb} onChange={(event) => setMinFileSizeKb(event.target.value)} className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 px-3 text-sm outline-none focus:border-[#F19B84] focus:ring-2 focus:ring-[#FCE5DE]" />
                    </label>
                    <label className="flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 md:col-span-2 md:mt-[26px]">
                      <input type="checkbox" checked={ignoreHidden} onChange={(event) => setIgnoreHidden(event.target.checked)} />
                      <I18nText>忽略隐藏文件</I18nText></label>
                  </div>
                ) : null}
                {message ? <div className="md:col-span-12 rounded-2xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div> : null}
                {error ? <div className="md:col-span-12 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
              </form> : null}
              <div className="space-y-3">
                {folders.map((path) => (
                  <div key={path.id} className="rounded-[20px] border border-slate-200 bg-white p-4">
                    <div className="flex flex-col gap-4 md:flex-row md:items-center">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#fff0ea] text-[#d94724]">
                        <FolderOpen size={18} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-semibold">{path.name}</div>
                        <div className="break-words text-sm text-slate-500">{path.rootPath}</div>
                        <div className="mt-2 text-xs text-slate-500"><I18nText>引用原文件</I18nText> · {i18nAttribute(organizationModeLabel(path.organizationMode))} · {path.ignoreHidden ? i18nAttribute("忽略隐藏文件") : i18nAttribute("包含隐藏文件")} <I18nText>· 小于 </I18nText>{Math.round((path.minFileSizeBytes ?? 0) / 1024)} <I18nText>KB 跳过</I18nText></div>
                      </div>
                      <button disabled={pathBusy === `toggle:${path.id}`} onClick={() => togglePath(path)} className={cn('h-7 w-12 rounded-full p-1 transition disabled:cursor-not-allowed disabled:opacity-60', path.enabled ? 'bg-[#ff4f26]' : 'bg-slate-300')} aria-label={i18nAttribute("启用书库")}>
                        <span className={cn('block h-5 w-5 rounded-full bg-white transition', path.enabled && 'translate-x-5')} />
                      </button>
                      <Button
                        type="button"
                        variant="secondary"
                        icon={Settings2}
                        onClick={() => setExpandedRules((current) => ({ ...current, [path.id]: !current[path.id] }))}
                        aria-expanded={Boolean(expandedRules[path.id])}
                      >
                        <I18nText>设置</I18nText></Button>
                      <Button variant="danger" icon={Trash2} loading={pathBusy === `delete:${path.id}`} loadingText={i18nAttribute("删除中")} onClick={() => deletePath(path)}><I18nText>删除</I18nText></Button>
                    </div>
                    {expandedRules[path.id] ? (
                      <div className="mt-4 border-t border-slate-100 pt-4">
                        <LibraryEditor path={path} saving={ruleBusy === path.id} onSave={saveFolderSettings} compact />
                      </div>
                    ) : null}
                  </div>
                ))}
                {folders.length === 0 ? <div className="rounded-3xl bg-slate-50 p-6 text-sm text-slate-500"><I18nText>尚未保存书库。</I18nText></div> : null}
              </div>
            </div>
          ) : active === '备份与恢复' ? (
            <div className="mt-6 space-y-5">
              <div className="flex flex-col gap-4 rounded-3xl border border-slate-200 bg-slate-50 p-5 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="font-semibold"><I18nText>备份范围</I18nText></div>
                  <div className="mt-1 text-sm leading-6 text-slate-500"><I18nText>仅包含系统设置和数据库数据，包括读物元数据、标签、阅读进度、书库配置和封面缓存索引；不包含原始读物文件或封面图片文件。</I18nText></div>
                  <div className="mt-2 text-xs text-slate-500"><I18nText>当前支持手动备份；恢复备份会覆盖数据库中的相关记录。</I18nText></div>
                </div>
                <Button icon={Save} onClick={createBackup} loading={backupBusy === 'create'} loadingText={i18nAttribute("创建中")}><I18nText>备份</I18nText></Button>
              </div>
              {message ? <div className="rounded-2xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div> : null}
              {error ? <div className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
              <div className="space-y-3">
                {backups.map((backup) => (
                  <div key={backup.id} className="flex flex-col gap-4 rounded-3xl border border-slate-200 bg-white p-5 md:flex-row md:items-center">
                    <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#fff0ea] text-[#d94724]">
                      <Database size={18} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">{backup.filename}</span>
                        <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">{backup.kind === 'automatic' ? i18nAttribute("自动") : backup.kind === 'manual' ? i18nAttribute("手动") : i18nAttribute("未知")}</span>
                      </div>
                      <div className="mt-1 text-sm text-slate-500">{new Date(backup.createdAt).toLocaleString(locale)} · {formatBytes(backup.sizeBytes)}</div>
                      {backup.counts ? (
                        <div className="mt-2 text-xs text-slate-500">
                          {backup.counts.books} <I18nText>本图书 · </I18nText>{backup.counts.readingProgresses} <I18nText>条阅读进度 · </I18nText>{backup.counts.libraries} <I18nText>个书库</I18nText></div>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button variant="secondary" icon={Download} onClick={() => downloadBackup(backup)}><I18nText>下载</I18nText></Button>
                      <Button variant="secondary" icon={RotateCcw} onClick={() => restoreBackup(backup)} loading={backupBusy === `restore:${backup.id}`} loadingText={i18nAttribute("恢复中")}><I18nText>恢复</I18nText></Button>
                      <Button variant="danger" icon={Trash2} onClick={() => deleteBackup(backup)} loading={backupBusy === `delete:${backup.id}`} loadingText={i18nAttribute("删除中")}><I18nText>删除</I18nText></Button>
                    </div>
                  </div>
                ))}
                {backups.length === 0 ? <div className="rounded-3xl bg-slate-50 p-6 text-sm text-slate-500"><I18nText>尚未创建备份。</I18nText></div> : null}
              </div>
            </div>
          ) : (
            null
          )}
        </div>
      </div>
    </div>
  );
}

function LibraryEditor({
  path,
  saving,
  onSave,
  compact = false
}: {
  path: Library;
  saving: boolean;
  onSave: (path: Library, updates: Pick<Library, 'name' | 'rootPath' | 'ignorePatterns' | 'ignoreHidden' | 'minFileSizeBytes' | 'organizationMode'>) => Promise<void>;
  compact?: boolean;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  const [folderName, setFolderName] = useState(path.name);
  const [folderPath, setFolderPath] = useState(path.rootPath);
  const [patterns, setPatterns] = useState(path.ignorePatterns ?? '');
  const [hidden, setHidden] = useState(path.ignoreHidden);
  const [minSizeKb, setMinSizeKb] = useState(String(Math.round((path.minFileSizeBytes ?? 0) / 1024)));
  const [mode, setMode] = useState<OrganizationMode>(path.organizationMode);
  useEffect(() => {
    setFolderName(path.name);
    setFolderPath(path.rootPath);
    setPatterns(path.ignorePatterns ?? '');
    setHidden(path.ignoreHidden);
    setMinSizeKb(String(Math.round((path.minFileSizeBytes ?? 0) / 1024)));
    setMode(path.organizationMode);
  }, [path]);

  return (
    <div className={cn(!compact && 'rounded-3xl border border-slate-200 bg-slate-50 p-5')}>
      <div className="grid gap-4 md:grid-cols-12">
        <label className="md:col-span-4">
          <span className="text-sm font-medium text-slate-700"><I18nText>名称</I18nText></span>
          <input value={folderName} onChange={(event) => setFolderName(event.target.value)} className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm outline-none focus:border-[#F19B84] focus:ring-2 focus:ring-[#FCE5DE]" />
        </label>
        <div className="md:col-span-8">
          <span className="text-sm font-medium text-slate-700"><I18nText>书库路径</I18nText></span>
          <SharedDirectoryPathPicker value={folderPath} onChange={setFolderPath} compact />
        </div>
        <label className="flex h-10 items-center gap-3 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 md:col-span-4 md:mt-[26px]">
          <input type="checkbox" checked={hidden} onChange={(event) => setHidden(event.target.checked)} />
          <I18nText>忽略隐藏文件</I18nText></label>
        <label className="md:col-span-4">
          <span className="text-sm font-medium text-slate-700"><I18nText>最小文件大小 KB</I18nText></span>
          <input
            type="number"
            min={0}
            value={minSizeKb}
            onChange={(event) => setMinSizeKb(event.target.value)}
            className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none focus:border-[#F19B84] focus:ring-2 focus:ring-[#FCE5DE]"
          />
        </label>
        <label className="md:col-span-4">
          <span className="text-sm font-medium text-slate-700"><I18nText>组织方式</I18nText></span>
          <Select value={mode} onChange={(value) => setMode(value as OrganizationMode)} ariaLabel="组织方式" className="mt-1.5 w-full" size="sm" options={ORGANIZATION_MODE_OPTIONS.map((option) => ({ value: option.value, label: option.label }))} />
        </label>
      </div>
      <div className="mt-2 text-xs leading-5 text-slate-500">{i18nAttribute(organizationModeDescription(mode))}</div>
      <label className="mt-4 block">
        <span className="text-sm font-medium text-slate-700"><I18nText>自定义忽略规则</I18nText></span>
        <textarea
          value={patterns}
          onChange={(event) => setPatterns(event.target.value)}
          rows={4}
          placeholder={i18nAttribute("每行一条 glob 规则，例如 **/temp/**")}
          className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-sm outline-none focus:border-[#F19B84] focus:ring-2 focus:ring-[#FCE5DE]"
        />
      </label>
      <div className="mt-2 text-xs leading-5 text-slate-500"><I18nText>默认已忽略封面、缩略图、临时文件、说明文件和普通图片；这里填写额外规则，每行一条。</I18nText></div>
      <div className="mt-3 flex justify-end">
        <Button
          type="button"
          icon={CheckCircle2}
          loading={saving}
          loadingText={i18nAttribute("保存中")}
          disabled={!folderName.trim() || !folderPath.trim()}
          onClick={() => onSave(path, {
            name: folderName.trim(),
            rootPath: folderPath,
            ignorePatterns: patterns,
            ignoreHidden: hidden,
            organizationMode: mode,
            minFileSizeBytes: Math.max(0, Math.round(Number(minSizeKb || 0) * 1024))
          })}
        >
          <I18nText>保存设置</I18nText></Button>
      </div>
    </div>
  );
}
