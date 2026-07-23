'use client';

import { ChevronRight, Folder, FolderOpen, RefreshCw, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import { useToast } from '../../../components/ui/feedback';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { useI18n as useExpressionI18n } from '@/i18n/provider';

type MonitorFolder = {
  id: string;
  name: string;
  rootPath: string;
  enabled: boolean;
};

type DirectoryNode = {
  name: string;
  path: string;
  readable: boolean;
  error?: string | null;
  children: Array<{ name: string; path: string; readable: boolean }>;
};

type ScanResult = {
  path: string;
  monitorFolderName?: string | null;
  directoriesScanned: number;
  filesScanned: number;
  candidatesFound: number;
  queued: number;
  skipped: number;
  errors: Array<{ path: string; error: string }>;
};

function normalizePath(value: string) {
  return value.replace(/\/+$/, '') || value;
}

function isInside(rootPath: string, targetPath: string) {
  const root = normalizePath(rootPath);
  const target = normalizePath(targetPath);
  return target === root || target.startsWith(`${root}/`);
}

export function ImportFileManager() {
  const { t: i18nAttribute } = useAttributeI18n();
  const [folders, setFolders] = useState<MonitorFolder[]>([]);
  const [rootPath, setRootPath] = useState('');
  const [nodes, setNodes] = useState<Record<string, DirectoryNode>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedPath, setSelectedPath] = useState('');
  const [loadingPath, setLoadingPath] = useState('');
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ScanResult | null>(null);
  const toast = useToast();

  const loadNode = useCallback(async (path?: string) => {
    const key = path || '__root__';
    setLoadingPath(key);
    setError('');
    try {
      const response = await fetch(`/api/monitor-folders/tree${path ? `?path=${encodeURIComponent(path)}` : ''}`);
      const payload = await response.json() as { ok: boolean; data?: { node: DirectoryNode; monitorRoot?: string | null }; error?: { message: string } };
      if (!response.ok || !payload.ok || !payload.data?.node) throw new Error(payload.error?.message ?? '读取目录失败');
      const node = payload.data.node;
      setRootPath(payload.data.monitorRoot || node.path);
      setNodes((current) => ({ ...current, [node.path]: node }));
      return node;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取目录失败');
      return null;
    } finally {
      setLoadingPath('');
    }
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch('/api/monitor-folders');
        const payload = await response.json() as { ok: boolean; data?: { folders: MonitorFolder[] }; error?: { message: string } };
        if (!active) return;
        if (!response.ok || !payload.ok) throw new Error(payload.error?.message ?? '读取监控文件夹失败');
        setFolders(payload.data?.folders ?? []);
        const root = await loadNode();
        if (active && root) {
          setSelectedPath(root.path);
          setExpanded(new Set([root.path]));
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : '读取目录失败');
      }
    }
    void load();
    return () => { active = false; };
  }, [loadNode]);

  const selectedMonitorFolder = useMemo(() => folders
    .filter((folder) => folder.enabled && selectedPath && isInside(folder.rootPath, selectedPath))
    .sort((left, right) => right.rootPath.length - left.rootPath.length)[0] ?? null, [folders, selectedPath]);

  async function toggle(path: string) {
    const next = new Set(expanded);
    if (next.has(path)) {
      next.delete(path);
      setExpanded(next);
      return;
    }
    next.add(path);
    setExpanded(next);
    if (!nodes[path]) await loadNode(path);
  }

  async function scanSelectedDirectory() {
    if (!selectedPath || !selectedMonitorFolder) return;
    setScanning(true);
    setError('');
    setResult(null);
    try {
      const response = await fetch('/api/import-tasks/scan-directory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: selectedPath })
      });
      const payload = await response.json() as { ok: boolean; data?: ScanResult; error?: { message: string } };
      if (!response.ok || !payload.ok || !payload.data) throw new Error(payload.error?.message ?? '识别目录失败');
      setResult(payload.data);
      toast.success('目录扫描完成', `新增 ${payload.data.queued} 条导入任务，跳过 ${payload.data.skipped} 项`);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '识别目录失败';
      setError(message);
      toast.error('识别目录失败', message);
    } finally {
      setScanning(false);
    }
  }

  const rootNode = rootPath ? nodes[rootPath] : Object.values(nodes)[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 rounded-[20px] border border-[#DEDAD4] bg-[#FAF9F7] p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="font-semibold text-[#2A2825]"><I18nText>从目录识别图书</I18nText></div>
          <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>选择已启用监控文件夹内的目录。识别仍会应用格式、隐藏文件、大小、忽略规则和已导入检查。</I18nText></p>
        </div>
        <Button variant="secondary" icon={RefreshCw} loading={loadingPath === (selectedPath || '__root__')} loadingText={i18nAttribute("刷新中")} onClick={() => void loadNode(selectedPath || undefined)}><I18nText>刷新目录</I18nText></Button>
      </div>

      <div className="grid min-h-[420px] overflow-hidden rounded-[20px] border border-[#DEDAD4] bg-white md:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 border-b border-[#DEDAD4] p-3 md:border-b-0 md:border-r">
          <div className="mb-2 px-2 text-xs font-medium text-[#8A847D]"><I18nText>文件夹视图</I18nText></div>
          <div className="max-h-[520px] overflow-auto">
            {rootNode ? <DirectoryRow node={rootNode} level={0} nodes={nodes} expanded={expanded} selectedPath={selectedPath} loadingPath={loadingPath} onToggle={toggle} onSelect={setSelectedPath} /> : <div className="p-5 text-sm text-[#77716A]">{loadingPath ? i18nAttribute("正在读取目录…") : i18nAttribute("暂无可浏览目录")}</div>}
          </div>
        </div>
        <aside className="flex flex-col p-5">
          <div className="text-xs font-medium text-[#8A847D]"><I18nText>当前选择</I18nText></div>
          <div className="mt-2 break-all text-sm font-semibold leading-6 text-[#2A2825]">{selectedPath || i18nAttribute("尚未选择目录")}</div>
          <div className={cn('mt-4 rounded-xl px-3 py-2 text-xs leading-5', selectedMonitorFolder ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800')}>
            {selectedMonitorFolder ? i18nAttribute("使用“{value0}”的识别规则", { value0: selectedMonitorFolder.name }) : i18nAttribute("此目录不在已启用的监控文件夹内，不能识别。")}
          </div>
          {result ? (
            <div className="mt-4 space-y-2 border-t border-[#E9E5DF] pt-4 text-sm text-[#5F5953]">
              <div><I18nText>扫描目录：</I18nText>{result.directoriesScanned}</div>
              <div><I18nText>检查文件：</I18nText>{result.filesScanned}</div>
              <div><I18nText>加入队列：</I18nText>{result.queued}</div>
              <div><I18nText>按规则跳过：</I18nText>{result.skipped}</div>
              {result.errors.length > 0 ? <div className="text-red-600"><I18nText>读取失败：</I18nText>{result.errors.length}</div> : null}
            </div>
          ) : null}
          {error ? <div className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{error}</div> : null}
          <Button className="mt-auto w-full" icon={Search} disabled={!selectedMonitorFolder || !selectedPath} loading={scanning} loadingText={i18nAttribute("识别中")} onClick={() => void scanSelectedDirectory()}><I18nText>识别此目录</I18nText></Button>
        </aside>
      </div>
    </div>
  );
}

function DirectoryRow({ node, level, nodes, expanded, selectedPath, loadingPath, onToggle, onSelect }: {
  node: DirectoryNode;
  level: number;
  nodes: Record<string, DirectoryNode>;
  expanded: Set<string>;
  selectedPath: string;
  loadingPath: string;
  onToggle: (path: string) => Promise<void>;
  onSelect: (path: string) => void;
}) {
  const { t: i18nExpression } = useExpressionI18n();
  const isExpanded = expanded.has(node.path);
  const children = nodes[node.path]?.children ?? node.children;
  return (
    <div>
      <div className={cn('group flex min-h-10 items-center rounded-xl pr-2 text-sm', selectedPath === node.path ? 'bg-[#FCE5DE] text-[#C84226]' : 'text-[#4F4A45] hover:bg-[#F7F4F0]')} style={{ paddingLeft: `${Math.min(level, 8) * 16 + 6}px` }}>
        <button type="button" onClick={() => void onToggle(node.path)} className="flex h-8 w-8 shrink-0 items-center justify-center" aria-label={isExpanded ? i18nExpression("收起 {value0}", { value0: node.name }) : i18nExpression("展开 {value0}", { value0: node.name })}>
          <ChevronRight size={15} className={cn('transition-transform', isExpanded && 'rotate-90')} />
        </button>
        <button type="button" onClick={() => onSelect(node.path)} disabled={!node.readable} className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left disabled:opacity-45">
          {isExpanded ? <FolderOpen size={17} className="shrink-0" /> : <Folder size={17} className="shrink-0" />}
          <span className="truncate">{node.name}</span>
          {loadingPath === node.path ? <span className="text-xs text-[#8A847D]"><I18nText>读取中</I18nText></span> : null}
        </button>
      </div>
      {isExpanded ? children.map((child) => (
        <DirectoryRow
          key={child.path}
          node={nodes[child.path] ?? { ...child, children: [] }}
          level={level + 1}
          nodes={nodes}
          expanded={expanded}
          selectedPath={selectedPath}
          loadingPath={loadingPath}
          onToggle={onToggle}
          onSelect={onSelect}
        />
      )) : null}
    </div>
  );
}
