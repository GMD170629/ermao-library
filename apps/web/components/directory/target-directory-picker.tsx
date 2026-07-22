'use client';

import { ChevronDown, ChevronRight, FolderOpen, RotateCcw } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { cn } from '../ui/cn';

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

type MonitorFoldersPayload = {
  folders: MonitorFolder[];
  monitorRoot?: string | null;
  lastUploadTargetPath?: string | null;
  lastDownloadTargetPath?: string | null;
};

export type TargetDirectoryStatus = {
  autoImport: boolean;
  label: string;
};

function normalizePath(path: string) {
  return path.replace(/\/+$/, '') || path;
}

function isPathInside(rootPath: string, targetPath: string) {
  const root = normalizePath(rootPath);
  const target = normalizePath(targetPath);
  return target === root || target.startsWith(`${root}/`);
}

function autoImportFor(path: string, folders: MonitorFolder[]) {
  return folders.some((folder) => folder.enabled && isPathInside(folder.rootPath, path));
}

export function TargetDirectoryPicker({
  value,
  onChange,
  memory,
  label,
  requiredMessage,
  showRequiredState = true,
  processingMode = 'monitor',
  onStatusChange,
  className
}: {
  value: string;
  onChange: (value: string) => void;
  memory: 'upload' | 'download';
  label: string;
  requiredMessage: string;
  showRequiredState?: boolean;
  processingMode?: 'monitor' | 'queue';
  onStatusChange?: (status: TargetDirectoryStatus) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [monitorRoot, setMonitorRoot] = useState('');
  const [folders, setFolders] = useState<MonitorFolder[]>([]);
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
    let active = true;
    async function loadInitialState() {
      try {
        const response = await fetch('/api/monitor-folders');
        const payload = (await response.json()) as { ok: boolean; data?: MonitorFoldersPayload; error?: { message: string } };
        if (!active) return;
        if (payload.ok) {
          const nextFolders = payload.data?.folders ?? [];
          setFolders(nextFolders);
          const lastPath = memory === 'upload' ? payload.data?.lastUploadTargetPath : payload.data?.lastDownloadTargetPath;
          const rootNode = await loadNode();
          if (!active) return;
          if (lastPath) {
            const lastNode = await loadNode(lastPath);
            if (active && lastNode) onChange(lastNode.path);
          } else if (rootNode) {
            setMonitorRoot(payload.data?.monitorRoot || rootNode.path);
          }
        } else {
          setTreeError(payload.error?.message ?? '读取目录失败');
        }
      } catch {
        if (active) setTreeError('读取目录失败');
      }
    }
    void loadInitialState();
    return () => {
      active = false;
    };
  }, [memory, onChange]);

  useEffect(() => {
    if (!open) return;
    function closeOnOutside(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', closeOnOutside);
    return () => document.removeEventListener('mousedown', closeOnOutside);
  }, [open]);

  useEffect(() => {
    if (!onStatusChange) return;
    const autoImport = processingMode === 'queue' ? Boolean(value) : value ? autoImportFor(value, folders) : false;
    onStatusChange({
      autoImport,
      label: value
        ? processingMode === 'queue'
          ? '上传文件会由后台自动处理并导入书库'
          : autoImport
            ? '该目录会自动入库'
            : '该目录未启用监控，仅保存文件'
        : requiredMessage
    });
  }, [folders, onStatusChange, processingMode, requiredMessage, value]);

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
  const selectedAutoImport = processingMode === 'queue' ? Boolean(value) : value ? autoImportFor(value, folders) : false;

  return (
    <div ref={rootRef} className={cn('relative', className)}>
      <label className="text-sm text-slate-600">
        {label}
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className={cn(
            'mt-2 flex h-11 w-full min-w-0 items-center gap-2 rounded-2xl border bg-white px-4 text-left text-sm outline-none transition focus:border-blue-300 focus:ring-4 focus:ring-blue-100',
            value ? 'border-slate-200 text-slate-900' : showRequiredState ? 'border-red-200 text-slate-400' : 'border-slate-200 text-slate-500'
          )}
          aria-expanded={open}
        >
          <FolderOpen size={16} className="shrink-0 text-slate-500" />
          <span className="min-w-0 flex-1 truncate">{value || requiredMessage}</span>
          <ChevronDown size={16} className={cn('shrink-0 text-slate-400 transition', open && 'rotate-180')} />
        </button>
      </label>
      <div className={cn('mt-2 text-xs leading-5', value ? (selectedAutoImport ? 'text-emerald-700' : 'text-amber-700') : showRequiredState ? 'text-red-600' : 'text-slate-500')}>
        {value
          ? processingMode === 'queue'
            ? '上传文件会由后台自动处理并导入书库'
            : selectedAutoImport
              ? '该目录会自动入库'
              : '该目录未启用监控，仅保存文件'
          : requiredMessage}
      </div>
      {open ? (
        <div className="absolute left-0 right-0 top-full z-50 mt-2 rounded-2xl border border-slate-200 bg-white p-3 text-sm text-slate-700 shadow-xl shadow-slate-200/60">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="font-medium text-slate-950">监控根目录</div>
              <div className="truncate text-xs text-slate-500">{monitorRoot || '读取中'}</div>
            </div>
            <button
              type="button"
              onClick={() => loadNode(value || monitorRoot || undefined)}
              className="inline-flex h-9 items-center gap-2 rounded-xl border border-slate-200 px-3 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              <RotateCcw size={14} />
              刷新
            </button>
          </div>
          <div className="max-h-72 overflow-auto rounded-xl bg-slate-50 p-2">
            {rootNode ? (
              <TargetDirectoryNodeRow
                node={rootNode}
                level={0}
                selectedPath={value}
                folders={folders}
                nodes={nodes}
                expanded={expanded}
                loadingPath={loadingPath}
                onSelect={selectPath}
                onToggle={toggleDirectory}
              />
            ) : (
              <div className="px-3 py-2 text-slate-500">{loadingPath ? '正在读取目录...' : '暂无可选目录'}</div>
            )}
          </div>
          {treeError ? <div className="mt-2 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">{treeError}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function TargetDirectoryNodeRow({
  node,
  level,
  selectedPath,
  folders,
  nodes,
  expanded,
  loadingPath,
  onSelect,
  onToggle
}: {
  node: DirectoryNode;
  level: number;
  selectedPath: string;
  folders: MonitorFolder[];
  nodes: Record<string, DirectoryNode>;
  expanded: Record<string, boolean>;
  loadingPath: string;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
}) {
  const isExpanded = Boolean(expanded[node.path]);
  const isSelected = selectedPath === node.path;
  const children = node.children ?? [];
  const autoImport = autoImportFor(node.path, folders);

  return (
    <div>
      <div className={cn('flex items-center gap-1 rounded-xl px-2 py-1.5', isSelected ? 'bg-blue-50 text-blue-700' : 'text-slate-700 hover:bg-white')} style={{ paddingLeft: `${8 + level * 18}px` }}>
        <button
          type="button"
          onClick={() => onToggle(node.path)}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
          aria-label={isExpanded ? '收起目录' : '展开目录'}
        >
          <ChevronRight size={15} className={cn('transition', isExpanded && 'rotate-90')} />
        </button>
        <button type="button" onClick={() => onSelect(node.path)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <FolderOpen size={15} className="shrink-0" />
          <span className="truncate">{node.path}</span>
        </button>
        {autoImport ? <span className="shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">自动入库</span> : null}
        {loadingPath === node.path ? <span className="shrink-0 text-xs text-slate-400">读取中</span> : null}
      </div>
      {isExpanded ? (
        <div>
          {children.length > 0 ? children.map((child) => {
            const childNode = nodes[child.path] ?? { ...child, children: [] };
            return (
              <TargetDirectoryNodeRow
                key={child.path}
                node={childNode}
                level={level + 1}
                selectedPath={selectedPath}
                folders={folders}
                nodes={nodes}
                expanded={expanded}
                loadingPath={loadingPath}
                onSelect={onSelect}
                onToggle={onToggle}
              />
            );
          }) : <div className="px-3 py-1.5 text-xs text-slate-400" style={{ paddingLeft: `${42 + level * 18}px` }}>没有子目录</div>}
        </div>
      ) : null}
    </div>
  );
}
