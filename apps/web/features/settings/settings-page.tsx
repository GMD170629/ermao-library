'use client';

import { CheckCircle2, ChevronDown, ChevronRight, Database, Download, FolderOpen, RotateCcw, Save, Settings2, SlidersHorizontal, Trash2 } from 'lucide-react';
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '../../components/ui/button';
import { cn } from '../../components/ui/cn';
import { useConfirm, useToast } from '../../components/ui/feedback';
import { useI18n } from '../../i18n/provider';
import { PageTitle } from '../../components/ui/page-title';
import { Select } from '../../components/ui/select';
import { withBasePath } from '../../lib/base-path';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { useI18n as useExpressionI18n } from '@/i18n/provider';

type MonitorFolder = {
  id: string;
  name: string;
  rootPath: string;
  enabled: boolean;
  ignorePatterns?: string | null;
  ignoreHidden: boolean;
  minFileSizeBytes: number;
  description?: string | null;
};

type MonitorFoldersPayload = {
  folders: MonitorFolder[];
  monitorRoot?: string;
  lastUploadTargetPath?: string | null;
  lastDownloadTargetPath?: string | null;
};

type BackupItem = {
  id: string;
  kind: 'manual' | 'automatic' | 'unknown';
  filename: string;
  sizeBytes: number;
  createdAt: string;
  counts?: {
    works: number;
    readingProgresses: number;
    monitorFolders: number;
  };
};

type DirectoryNode = {
  name: string;
  path: string;
  readable: boolean;
  error?: string | null;
  children: Array<{
    name: string;
    path: string;
    readable: boolean;
  }>;
};

type DirectoryTreePayload = {
  node: DirectoryNode;
  monitorRoot?: string | null;
};

type AppSettings = Record<string, string>;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function toggleExternalSettings(settings: AppSettings, enabled: boolean): AppSettings {
  return {
    ...settings,
    'metadata.external.enabled': String(enabled),
    'metadata.douban.enabled': String(enabled),
    'metadata.bangumi.enabled': String(enabled)
  };
}

function toggleExternalProvider(settings: AppSettings, providerKey: 'metadata.douban.enabled' | 'metadata.bangumi.enabled', enabled: boolean): AppSettings {
  return {
    ...settings,
    'metadata.external.enabled': String(enabled || settings['metadata.external.enabled'] === 'true'),
    [providerKey]: String(enabled)
  };
}

const editableSystemSettingKeys = new Set([
  'metadata.external.enabled',
  'metadata.douban.enabled',
  'metadata.douban.userAgent',
  'metadata.bangumi.enabled',
  'metadata.bangumi.baseUrl',
  'metadata.bangumi.accessToken',
  'metadata.bangumi.userAgent',
  'metadata.ai.enabled',
  'metadata.ai.baseUrl',
  'metadata.ai.apiKey',
  'metadata.ai.model'
]);

const sensitiveSystemSettingKeys = [
  'metadata.bangumi.accessToken',
  'metadata.ai.apiKey'
] as const;

function settingsForSave(settings: AppSettings) {
  const next: Record<string, string> = {};
  for (const [key, value] of Object.entries(settings)) {
    if (!editableSystemSettingKeys.has(key)) continue;
    if (sensitiveSystemSettingKeys.includes(key as (typeof sensitiveSystemSettingKeys)[number]) && !value.trim()) continue;
    next[key] = value;
  }
  return next;
}

export function SettingsPage({ embedded = false, initialSection }: { embedded?: boolean; initialSection?: string }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const { locale } = useI18n();
  const groups = ['监控文件夹', '备份与恢复', '元数据'];
  const [active, setActive] = useState(initialSection ?? '监控文件夹');
  const [folders, setFolders] = useState<MonitorFolder[]>([]);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [settings, setSettings] = useState<AppSettings>({
    'metadata.external.enabled': 'false',
    'metadata.douban.enabled': 'false',
    'metadata.douban.userAgent': 'ShukuStarship/0.1 (+https://github.com/GMD170629/ermao-library)',
    'metadata.bangumi.enabled': 'false',
    'metadata.bangumi.accessToken': '',
    'metadata.bangumi.userAgent': 'ShukuStarship/0.1 (https://github.com/GMD170629/ermao-library)',
    'metadata.ai.enabled': 'false',
    'metadata.ai.baseUrl': '',
    'metadata.ai.apiKey': '',
    'metadata.ai.model': ''
  });
  const [name, setName] = useState('我的监控文件夹');
  const [rootPath, setRootPath] = useState('/books');
  const [ignorePatterns, setIgnorePatterns] = useState('');
  const [ignoreHidden, setIgnoreHidden] = useState(true);
  const [minFileSizeKb, setMinFileSizeKb] = useState('0');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [backupBusy, setBackupBusy] = useState('');
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [pathBusy, setPathBusy] = useState('');
  const [ruleBusy, setRuleBusy] = useState('');
  const [showCreateFolder, setShowCreateFolder] = useState(false);
  const [showCreateRules, setShowCreateRules] = useState(false);
  const [pendingSecretClears, setPendingSecretClears] = useState<string[]>([]);
  const [expandedRules, setExpandedRules] = useState<Record<string, boolean>>({});
  const confirm = useConfirm();
  const toast = useToast();

  const loadPaths = useCallback(async () => {
    const response = await fetch('/api/monitor-folders');
    const payload = (await response.json()) as { ok: boolean; data?: MonitorFoldersPayload; error?: { message: string } };
    if (payload.ok) {
      setFolders(payload.data?.folders ?? []);
      setRootPath((current) => payload.data?.monitorRoot && current === '/books' ? payload.data.monitorRoot : current);
    } else {
      setError(payload.error?.message ?? '读取监控文件夹失败');
    }
  }, []);

  const loadBackups = useCallback(async () => {
    const response = await fetch('/api/backups');
    const payload = (await response.json()) as { ok: boolean; data?: { backups: BackupItem[] }; error?: { message: string } };
    if (payload.ok) setBackups(payload.data?.backups ?? []);
    else setError(payload.error?.message ?? '读取备份列表失败');
  }, []);

  useEffect(() => {
    if (active === '监控规则') setActive('监控文件夹');
  }, [active]);

  useEffect(() => {
    if (initialSection) setActive(initialSection);
  }, [initialSection]);

  useEffect(() => {
    if (!initialSection || initialSection === '监控文件夹') {
      void loadPaths();
    }
    if (!initialSection || initialSection === '备份与恢复') void loadBackups();
    if (initialSection === '监控文件夹' || initialSection === '备份与恢复') return;
    fetch('/api/system-settings').then((response) => response.json()).then((payload) => {
      if (!payload.ok) return;
      const loaded = { ...payload.data.settings } as Record<string, unknown>;
      const secretState = Object.fromEntries(sensitiveSystemSettingKeys.flatMap((key) => {
        const legacyValue = typeof loaded[key] === 'string' ? loaded[key].trim() : '';
        const configured = loaded[`${key}Configured`] === true || loaded[`${key}Configured`] === 'true' || Boolean(legacyValue);
        delete loaded[key];
        delete loaded[`${key}Configured`];
        return [[key, ''], [`${key}Configured`, String(configured)]];
      }));
      delete loaded.theme;
      delete loaded.timezone;
      delete loaded.language;
      setSettings((current) => ({
        ...current,
        ...Object.fromEntries(Object.entries(loaded).map(([key, value]) => [key, typeof value === 'string' ? value : String(value ?? '')])),
        ...secretState
      }));
    }).catch(() => undefined);
  }, [initialSection, loadBackups, loadPaths]);

  async function savePath(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setMessage('');
    setPathBusy('create');
    const response = await fetch('/api/monitor-folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, rootPath, enabled: true, ignorePatterns, ignoreHidden, minFileSizeBytes: Math.max(0, Math.round(Number(minFileSizeKb || 0) * 1024)) })
    });
    const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
    if (!payload.ok) {
      const nextError = payload.error?.message ?? '保存失败';
      setError(nextError);
      toast.error('保存失败', nextError);
      setPathBusy('');
      return;
    }
    setMessage('监控文件夹已保存');
    toast.success('监控文件夹已保存');
    await loadPaths();
    setShowCreateFolder(false);
    setShowCreateRules(false);
    setPathBusy('');
  }

  async function togglePath(path: MonitorFolder) {
    setPathBusy(`toggle:${path.id}`);
    await fetch(`/api/monitor-folders/${path.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !path.enabled })
    });
    await loadPaths();
    toast.success(path.enabled ? '监控文件夹已停用' : '监控文件夹已启用');
    setPathBusy('');
  }

  async function deletePath(path: MonitorFolder) {
    const confirmed = await confirm({
      title: '删除监控文件夹',
      description: `删除监控文件夹“${path.name}”？不会删除原始读物文件。`,
      confirmLabel: '删除',
      tone: 'danger'
    });
    if (!confirmed) return;
    setPathBusy(`delete:${path.id}`);
    await fetch(`/api/monitor-folders/${path.id}`, { method: 'DELETE' });
    await loadPaths();
    toast.success('监控文件夹已删除');
    setPathBusy('');
  }

  async function saveFolderSettings(path: MonitorFolder, updates: Pick<MonitorFolder, 'name' | 'rootPath' | 'ignorePatterns' | 'ignoreHidden' | 'minFileSizeBytes'>) {
    setError('');
    setMessage('');
    setRuleBusy(path.id);
    const response = await fetch(`/api/monitor-folders/${path.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
    if (!payload.ok) {
      const nextError = payload.error?.message ?? '保存监控文件夹设置失败';
      setError(nextError);
      toast.error('保存监控文件夹设置失败', nextError);
      setRuleBusy('');
      return;
    }
    setMessage('监控文件夹设置已保存');
    toast.success('监控文件夹设置已保存');
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
      description: '恢复备份会覆盖当前读物元数据、标签、阅读进度和监控文件夹配置，但不会删除原始读物文件。是否继续？',
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

  async function saveSettings() {
    setError('');
    setMessage('');
    setSettingsBusy(true);
    const settingsToSave = settingsForSave(settings);
    const clearSensitiveKeys = [...pendingSecretClears];
    const response = await fetch('/api/system-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: settingsToSave, clearSensitiveKeys })
    });
    const payload = (await response.json()) as { ok: boolean; error?: { message: string } };
    setSettingsBusy(false);
    if (!payload.ok) {
      const nextError = payload.error?.message ?? '保存设置失败';
      setError(nextError);
      toast.error('保存设置失败', nextError);
    } else {
      const nextSecretState = Object.fromEntries(sensitiveSystemSettingKeys.flatMap((key) => [
        [key, ''],
        [`${key}Configured`, clearSensitiveKeys.includes(key) ? 'false' : settingsToSave[key] ? 'true' : settings[`${key}Configured`] ?? 'false']
      ]));
      setSettings((current) => ({
        ...current,
        ...settingsToSave,
        ...nextSecretState
      }));
      setMessage('系统设置已保存');
      toast.success('系统设置已保存');
      setPendingSecretClears([]);
      window.dispatchEvent(new Event('shuku:settings-changed'));
    }
  }

  function updateSecret(key: (typeof sensitiveSystemSettingKeys)[number], value: string) {
    setSettings((current) => ({ ...current, [key]: value }));
    if (value.trim()) setPendingSecretClears((current) => current.filter((item) => item !== key));
  }

  function toggleSecretClear(key: (typeof sensitiveSystemSettingKeys)[number]) {
    const pending = pendingSecretClears.includes(key);
    setPendingSecretClears((current) => pending ? current.filter((item) => item !== key) : [...new Set([...current, key])]);
    setSettings((current) => ({ ...current, [key]: '', [`${key}Configured`]: pending ? 'true' : 'false' }));
  }

  return (
    <div className={embedded ? '' : 'space-y-6'}>
      {!embedded ? <PageTitle
        title={i18nAttribute("系统设置")}
        desc={i18nAttribute("配置监控导入、备份、智能整理和外部来源。")}
        action={active === '元数据' ? <Button icon={CheckCircle2} loading={settingsBusy} loadingText={i18nAttribute("保存中")} onClick={saveSettings}><I18nText>保存设置</I18nText></Button> : undefined}
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
          {active === '监控文件夹' ? (
            <div className="mt-6 space-y-5">
              <div className="flex justify-end">
                <Button type="button" variant="secondary" icon={FolderOpen} onClick={() => setShowCreateFolder((current) => !current)}>
                  {showCreateFolder ? i18nAttribute("收起添加表单") : i18nAttribute("添加文件夹")}
                </Button>
              </div>
              {showCreateFolder ? <form onSubmit={savePath} className="grid grid-cols-1 gap-3 rounded-[20px] border border-slate-200 bg-slate-50 p-4 md:grid-cols-12 md:items-end">
                <label className="md:col-span-3">
                  <span className="text-sm font-medium text-slate-700"><I18nText>名称</I18nText></span>
                  <input value={name} onChange={(event) => setName(event.target.value)} className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 px-3 text-sm outline-none focus:border-[#F19B84] focus:ring-2 focus:ring-[#FCE5DE]" />
                </label>
                <div className="md:col-span-7">
                  <span className="text-sm font-medium text-slate-700"><I18nText>监控文件夹路径</I18nText></span>
                  <DirectoryPathPicker value={rootPath} onChange={setRootPath} compact />
                </div>
                <div className="md:col-span-2">
                  <Button className="h-10 w-full" icon={FolderOpen} loading={pathBusy === 'create'} loadingText={i18nAttribute("保存中")}><I18nText>保存</I18nText></Button>
                </div>
                <div className="text-xs leading-5 text-slate-500 md:col-span-12"><I18nText>图书会进入书库；每位用户可按来源文件夹创建自己的智能书架。</I18nText></div>
                <button
                  type="button"
                  aria-expanded={showCreateRules}
                  onClick={() => setShowCreateRules((current) => !current)}
                  className="flex min-h-9 items-center gap-2 text-left text-sm font-medium text-slate-600 hover:text-[#D94724] md:col-span-12"
                >
                  <SlidersHorizontal size={15} />
                  <I18nText>扫描规则</I18nText><ChevronDown size={15} className={cn('transition-transform', showCreateRules && 'rotate-180')} />
                  <span className="font-normal text-slate-400"><I18nText>默认忽略隐藏文件，不限制文件大小</I18nText></span>
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
                        <div className="mt-2 text-xs text-slate-500"><I18nText>引用原文件</I18nText> · {path.ignoreHidden ? i18nAttribute("忽略隐藏文件") : i18nAttribute("包含隐藏文件")} <I18nText>· 小于 </I18nText>{Math.round((path.minFileSizeBytes ?? 0) / 1024)} <I18nText>KB 跳过</I18nText></div>
                      </div>
                      <button disabled={pathBusy === `toggle:${path.id}`} onClick={() => togglePath(path)} className={cn('h-7 w-12 rounded-full p-1 transition disabled:cursor-not-allowed disabled:opacity-60', path.enabled ? 'bg-[#ff4f26]' : 'bg-slate-300')} aria-label={i18nAttribute("启用监控文件夹")}>
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
                        <MonitorFolderEditor path={path} saving={ruleBusy === path.id} onSave={saveFolderSettings} compact />
                      </div>
                    ) : null}
                  </div>
                ))}
                {folders.length === 0 ? <div className="rounded-3xl bg-slate-50 p-6 text-sm text-slate-500"><I18nText>尚未保存监控文件夹。</I18nText></div> : null}
              </div>
            </div>
          ) : active === '备份与恢复' ? (
            <div className="mt-6 space-y-5">
              <div className="flex flex-col gap-4 rounded-3xl border border-slate-200 bg-slate-50 p-5 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="font-semibold"><I18nText>备份范围</I18nText></div>
                  <div className="mt-1 text-sm leading-6 text-slate-500"><I18nText>仅包含系统设置和数据库数据，包括读物元数据、标签、阅读进度、监控文件夹配置和封面缓存索引；不包含原始读物文件或封面图片文件。</I18nText></div>
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
                          {backup.counts.works} <I18nText>部作品 · </I18nText>{backup.counts.readingProgresses} <I18nText>条阅读进度 · </I18nText>{backup.counts.monitorFolders} <I18nText>个监控文件夹</I18nText></div>
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
          ) : active === '元数据' ? (
            <div className="mt-6 space-y-5">
              <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <div className="font-semibold"><I18nText>外部数据源</I18nText></div>
                    <div className="mt-1 text-sm text-slate-500"><I18nText>电子书抓取豆瓣读书网页，漫画使用 Bangumi 官方 API。</I18nText></div>
                  </div>
                  <label className="flex items-center gap-3 rounded-2xl bg-white px-4 py-2 text-sm text-slate-700">
                    <input type="checkbox" checked={settings['metadata.external.enabled'] === 'true'} onChange={(event) => setSettings(toggleExternalSettings(settings, event.target.checked))} />
                    <I18nText>启用外部元数据</I18nText></label>
                </div>
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                <section className="rounded-3xl border border-slate-200 bg-white p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h2 className="font-semibold"><I18nText>豆瓣图书</I18nText></h2>
                      <p className="mt-1 text-sm text-slate-500"><I18nText>用于电子书，通过豆瓣读书网页抓取图书信息。</I18nText></p>
                    </div>
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input type="checkbox" checked={settings['metadata.douban.enabled'] === 'true'} onChange={(event) => setSettings(toggleExternalProvider(settings, 'metadata.douban.enabled', event.target.checked))} />
                      <I18nText>启用</I18nText></label>
                  </div>
                  <div className="mt-4 rounded-2xl bg-[#F7F4F0] px-4 py-3">
                    <div className="text-xs text-slate-500"><I18nText>获取方式</I18nText></div>
                    <div className="mt-1 text-sm font-medium text-slate-700"><I18nText>抓取网页</I18nText></div>
                  </div>
                  <label className="mt-4 block text-sm text-slate-600">
                    User-Agent
                    <input value={settings['metadata.douban.userAgent']} onChange={(event) => setSettings({ ...settings, 'metadata.douban.userAgent': event.target.value })} className="mt-2 h-11 w-full rounded-2xl border border-slate-200 px-4 text-sm outline-none" />
                  </label>
                </section>

                <section className="rounded-3xl border border-slate-200 bg-white p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h2 className="font-semibold"><I18nText>Bangumi 漫画</I18nText></h2>
                      <p className="mt-1 text-sm text-slate-500"><I18nText>用于漫画。User-Agent 为必填，Access Token 可选。</I18nText></p>
                    </div>
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input type="checkbox" checked={settings['metadata.bangumi.enabled'] === 'true'} onChange={(event) => setSettings(toggleExternalProvider(settings, 'metadata.bangumi.enabled', event.target.checked))} />
                      <I18nText>启用</I18nText></label>
                  </div>
                  <label className="mt-4 block text-sm text-slate-600">
                    User-Agent
                    <input value={settings['metadata.bangumi.userAgent']} onChange={(event) => setSettings({ ...settings, 'metadata.bangumi.userAgent': event.target.value })} className="mt-2 h-11 w-full rounded-2xl border border-slate-200 px-4 text-sm outline-none" />
                  </label>
                  <label className="mt-4 block text-sm text-slate-600">
                    Access Token
                    <input type="password" value={settings['metadata.bangumi.accessToken']} onChange={(event) => updateSecret('metadata.bangumi.accessToken', event.target.value)} placeholder={settings['metadata.bangumi.accessTokenConfigured'] === 'true' ? i18nAttribute("已配置；留空则保留原 Token") : i18nAttribute("输入 Access Token")} className="mt-2 h-11 w-full rounded-2xl border border-slate-200 px-4 text-sm outline-none" />
                    {settings['metadata.bangumi.accessTokenConfigured'] === 'true' || pendingSecretClears.includes('metadata.bangumi.accessToken') ? <button type="button" onClick={() => toggleSecretClear('metadata.bangumi.accessToken')} className="mt-2 text-xs font-medium text-[#D94724] hover:text-[#B83A1F]">{pendingSecretClears.includes('metadata.bangumi.accessToken') ? i18nAttribute("撤销清除") : i18nAttribute("清除已配置 Token")}</button> : null}
                  </label>
                </section>
              </div>

              <section className="rounded-3xl border border-slate-200 bg-white p-5">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <h2 className="font-semibold"><I18nText>AI 元数据识别</I18nText></h2>
                    <p className="mt-1 text-sm text-slate-500"><I18nText>使用 OpenAI-compatible Chat Completions，仅发送文件相对路径与文件名，不读取正文全文。</I18nText></p>
                  </div>
                  <label className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={settings['metadata.ai.enabled'] === 'true'} onChange={(event) => setSettings({ ...settings, 'metadata.ai.enabled': String(event.target.checked) })} />
                    <I18nText>启用</I18nText></label>
                </div>
                <div className="mt-4 grid gap-4 md:grid-cols-3">
                  <label className="text-sm text-slate-600">
                    <I18nText>API 地址</I18nText><input value={settings['metadata.ai.baseUrl']} onChange={(event) => setSettings({ ...settings, 'metadata.ai.baseUrl': event.target.value })} placeholder="https://api.openai.com/v1" className="mt-2 h-11 w-full rounded-2xl border border-slate-200 px-4 text-sm outline-none" />
                  </label>
                  <label className="text-sm text-slate-600">
                    <I18nText>模型</I18nText><input value={settings['metadata.ai.model']} onChange={(event) => setSettings({ ...settings, 'metadata.ai.model': event.target.value })} placeholder="gpt-4.1-mini" className="mt-2 h-11 w-full rounded-2xl border border-slate-200 px-4 text-sm outline-none" />
                  </label>
                  <label className="text-sm text-slate-600">
                    API Key
                    <input type="password" value={settings['metadata.ai.apiKey']} onChange={(event) => updateSecret('metadata.ai.apiKey', event.target.value)} placeholder={settings['metadata.ai.apiKeyConfigured'] === 'true' ? i18nAttribute("已配置；留空则保留原 Key") : i18nAttribute("输入 API Key")} className="mt-2 h-11 w-full rounded-2xl border border-slate-200 px-4 text-sm outline-none" />
                    {settings['metadata.ai.apiKeyConfigured'] === 'true' || pendingSecretClears.includes('metadata.ai.apiKey') ? <button type="button" onClick={() => toggleSecretClear('metadata.ai.apiKey')} className="mt-2 text-xs font-medium text-[#D94724] hover:text-[#B83A1F]">{pendingSecretClears.includes('metadata.ai.apiKey') ? i18nAttribute("撤销清除") : i18nAttribute("清除已配置 Key")}</button> : null}
                  </label>
                </div>
              </section>
              {message ? <div className="rounded-2xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div> : null}
              {error ? <div className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
            </div>
          ) : (
            null
          )}
        </div>
      </div>
      {embedded && active === '元数据' ? (
        <div className="mt-6 flex justify-end border-t border-[#DEDAD4] pt-5">
          <Button icon={CheckCircle2} loading={settingsBusy} loadingText={i18nAttribute("保存中")} onClick={saveSettings}><I18nText>保存更改</I18nText></Button>
        </div>
      ) : null}
    </div>
  );
}

function DirectoryPathPicker({ value, onChange, compact = false }: { value: string; onChange: (value: string) => void; compact?: boolean }) {
  const { t: i18nExpression } = useExpressionI18n();
  const [open, setOpen] = useState(false);
  const [monitorRoot, setMonitorRoot] = useState('');
  const [nodes, setNodes] = useState<Record<string, DirectoryNode>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loadingPath, setLoadingPath] = useState('');
  const [treeError, setTreeError] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);

  async function loadNode(path?: string) {
    setLoadingPath(path || '__root__');
    setTreeError('');
    try {
      const query = path ? `?path=${encodeURIComponent(path)}` : '';
      const response = await fetch(`/api/monitor-folders/tree${query}`);
      const payload = (await response.json()) as { ok: boolean; data?: DirectoryTreePayload; error?: { message: string } };
      if (!payload.ok || !payload.data?.node) {
        setTreeError(payload.error?.message ?? '读取目录树失败');
        return null;
      }
      const node = payload.data.node;
      setMonitorRoot(payload.data.monitorRoot || node.path);
      setNodes((current) => ({ ...current, [node.path]: node }));
      return node;
    } catch {
      setTreeError('读取目录树失败');
      return null;
    } finally {
      setLoadingPath('');
    }
  }

  useEffect(() => {
    loadNode();
  }, []);

  useEffect(() => {
    if (!open) return;
    function closeOnOutside(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', closeOnOutside);
    return () => document.removeEventListener('mousedown', closeOnOutside);
  }, [open]);

  async function toggleDirectory(path: string) {
    const nextExpanded = !expanded[path];
    setExpanded((current) => ({ ...current, [path]: nextExpanded }));
    if (nextExpanded && !nodes[path]) await loadNode(path);
  }

  function selectPath(path: string) {
    onChange(path);
    setOpen(false);
  }

  const rootNode = monitorRoot ? nodes[monitorRoot] : Object.values(nodes)[0];

  return (
    <div ref={rootRef} className={cn('relative', compact ? 'mt-1.5' : 'mt-2')}>
      <div className="flex gap-2">
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            'min-w-0 flex-1 border border-slate-200 bg-white text-sm outline-none',
            compact
              ? 'h-10 rounded-xl px-3 focus:border-[#F19B84] focus:ring-2 focus:ring-[#FCE5DE]'
              : 'h-11 rounded-2xl px-4 focus:border-blue-300 focus:ring-4 focus:ring-blue-100'
          )}
        />
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className={cn(
            'inline-flex shrink-0 items-center gap-2 border border-slate-200 bg-white text-sm font-medium text-slate-700 shadow-sm hover:border-[#f4b6a4] hover:bg-[#fff5f1] hover:text-[#d94724]',
            compact ? 'h-10 rounded-xl px-3' : 'h-11 rounded-2xl px-4'
          )}
          aria-expanded={open}
        >
          <FolderOpen size={16} />
          <I18nText>选择</I18nText><ChevronDown size={16} className={cn('transition', open && 'rotate-180')} />
        </button>
      </div>
      {open ? (
        <div className="absolute left-0 right-0 top-full z-50 mt-2 rounded-2xl border border-slate-200 bg-white p-3 text-sm text-slate-700 shadow-xl shadow-slate-200/60">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="font-medium text-slate-950"><I18nText>监控根目录</I18nText></div>
              <div className="truncate text-xs text-slate-500">{monitorRoot || i18nExpression("读取中")}</div>
            </div>
            <button
              type="button"
              onClick={() => loadNode(value || monitorRoot || undefined)}
              className="inline-flex h-9 items-center gap-2 rounded-xl border border-slate-200 px-3 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              <RotateCcw size={14} />
              <I18nText>刷新</I18nText></button>
          </div>
          <div className="max-h-72 overflow-auto rounded-xl bg-slate-50 p-2">
            {rootNode ? (
              <DirectoryNodeRow
                node={rootNode}
                level={0}
                selectedPath={value}
                nodes={nodes}
                expanded={expanded}
                loadingPath={loadingPath}
                onSelect={selectPath}
                onToggle={toggleDirectory}
              />
            ) : (
              <div className="px-3 py-2 text-slate-500">{loadingPath ? i18nExpression("正在读取目录...") : i18nExpression("暂无可选目录")}</div>
            )}
          </div>
          {treeError ? <div className="mt-2 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">{treeError}</div> : null}
          <div className="mt-2 text-xs leading-5 text-slate-500"><I18nText>只能浏览监控根目录内的目录；也可以直接粘贴路径。</I18nText></div>
        </div>
      ) : null}
    </div>
  );
}

function DirectoryNodeRow({
  node,
  level,
  selectedPath,
  nodes,
  expanded,
  loadingPath,
  onSelect,
  onToggle
}: {
  node: DirectoryNode;
  level: number;
  selectedPath: string;
  nodes: Record<string, DirectoryNode>;
  expanded: Record<string, boolean>;
  loadingPath: string;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
}) {
  const { t: i18nExpression } = useExpressionI18n();
  const isExpanded = Boolean(expanded[node.path]);
  const isSelected = selectedPath === node.path;
  const children = node.children ?? [];

  return (
    <div>
      <div className={cn('flex items-center gap-1 rounded-xl px-2 py-1.5', isSelected ? 'bg-[#fff0ea] text-[#d94724]' : 'text-slate-700 hover:bg-white')} style={{ paddingLeft: `${8 + level * 18}px` }}>
        <button
          type="button"
          onClick={() => onToggle(node.path)}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
          aria-label={isExpanded ? i18nExpression("收起目录") : i18nExpression("展开目录")}
        >
          <ChevronRight size={15} className={cn('transition', isExpanded && 'rotate-90')} />
        </button>
        <button type="button" onClick={() => onSelect(node.path)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <FolderOpen size={15} className="shrink-0" />
          <span className="truncate">{node.name || node.path}</span>
        </button>
        {loadingPath === node.path ? <span className="text-xs text-slate-400"><I18nText>读取中</I18nText></span> : null}
      </div>
      {isExpanded ? (
        <div>
          {children.length > 0 ? children.map((child) => {
            const childNode = nodes[child.path] ?? { ...child, children: [] };
            return (
              <DirectoryNodeRow
                key={child.path}
                node={childNode}
                level={level + 1}
                selectedPath={selectedPath}
                nodes={nodes}
                expanded={expanded}
                loadingPath={loadingPath}
                onSelect={onSelect}
                onToggle={onToggle}
              />
            );
          }) : <div className="px-3 py-1.5 text-xs text-slate-400" style={{ paddingLeft: `${42 + level * 18}px` }}><I18nText>没有子目录</I18nText></div>}
        </div>
      ) : null}
    </div>
  );
}

function MonitorFolderEditor({
  path,
  saving,
  onSave,
  compact = false
}: {
  path: MonitorFolder;
  saving: boolean;
  onSave: (path: MonitorFolder, updates: Pick<MonitorFolder, 'name' | 'rootPath' | 'ignorePatterns' | 'ignoreHidden' | 'minFileSizeBytes'>) => Promise<void>;
  compact?: boolean;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
  const [folderName, setFolderName] = useState(path.name);
  const [folderPath, setFolderPath] = useState(path.rootPath);
  const [patterns, setPatterns] = useState(path.ignorePatterns ?? '');
  const [hidden, setHidden] = useState(path.ignoreHidden);
  const [minSizeKb, setMinSizeKb] = useState(String(Math.round((path.minFileSizeBytes ?? 0) / 1024)));
  useEffect(() => {
    setFolderName(path.name);
    setFolderPath(path.rootPath);
    setPatterns(path.ignorePatterns ?? '');
    setHidden(path.ignoreHidden);
    setMinSizeKb(String(Math.round((path.minFileSizeBytes ?? 0) / 1024)));
  }, [path]);

  return (
    <div className={cn(!compact && 'rounded-3xl border border-slate-200 bg-slate-50 p-5')}>
      <div className="grid gap-4 md:grid-cols-12">
        <label className="md:col-span-4">
          <span className="text-sm font-medium text-slate-700"><I18nText>名称</I18nText></span>
          <input value={folderName} onChange={(event) => setFolderName(event.target.value)} className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm outline-none focus:border-[#F19B84] focus:ring-2 focus:ring-[#FCE5DE]" />
        </label>
        <div className="md:col-span-8">
          <span className="text-sm font-medium text-slate-700"><I18nText>监控文件夹路径</I18nText></span>
          <DirectoryPathPicker value={folderPath} onChange={setFolderPath} compact />
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
      </div>
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
            minFileSizeBytes: Math.max(0, Math.round(Number(minSizeKb || 0) * 1024))
          })}
        >
          <I18nText>保存设置</I18nText></Button>
      </div>
    </div>
  );
}
