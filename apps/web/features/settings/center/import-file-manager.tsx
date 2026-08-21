'use client';

import { ChevronRight, Folder, FolderOpen, RefreshCw, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import { useToast } from '../../../components/ui/feedback';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import { useI18n as useExpressionI18n } from '@/i18n/provider';
import { continueLibraryImport, type ContinueImportResult } from '../../import-tasks/public';

type Library = {
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
  const [folders, setFolders] = useState<Library[]>([]);
  const [rootPath, setRootPath] = useState('');
  const [nodes, setNodes] = useState<Record<string, DirectoryNode>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedPath, setSelectedPath] = useState('');
  const [loadingPath, setLoadingPath] = useState('');
  const [continuing, setContinuing] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ContinueImportResult | null>(null);
  const toast = useToast();

  const loadNode = useCallback(async (path?: string) => {
    const key = path || '__root__';
    setLoadingPath(key);
    setError('');
    try {
      const response = await fetch(`/api/libraries/tree${path ? `?path=${encodeURIComponent(path)}` : ''}`);
      const payload: unknown = await response.json().catch(() => null);
      const envelope = payload !== null && typeof payload === 'object' && !Array.isArray(payload) ? payload as Record<string, unknown> : {};
      const data = envelope.data !== null && typeof envelope.data === 'object' && !Array.isArray(envelope.data) ? envelope.data as Record<string, unknown> : {};
      const node = data.node !== null && typeof data.node === 'object' && !Array.isArray(data.node) ? data.node as DirectoryNode : null;
      const errorBody = envelope.error !== null && typeof envelope.error === 'object' && !Array.isArray(envelope.error) ? envelope.error as Record<string, unknown> : {};
      if (!response.ok || envelope.ok !== true || !node || typeof node.path !== 'string') {
        throw new Error(typeof errorBody.message === 'string' ? errorBody.message : i18nAttribute('读取目录失败'));
      }
      setRootPath(node.path);
      setNodes((current) => ({ ...current, [node.path]: node }));
      return node;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : i18nAttribute('读取目录失败'));
      return null;
    } finally {
      setLoadingPath('');
    }
  }, [i18nAttribute]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch('/api/libraries');
        const payload: unknown = await response.json().catch(() => null);
        const envelope = payload !== null && typeof payload === 'object' && !Array.isArray(payload) ? payload as Record<string, unknown> : {};
        const data = envelope.data !== null && typeof envelope.data === 'object' && !Array.isArray(envelope.data) ? envelope.data as Record<string, unknown> : {};
        const libraries = Array.isArray(data.libraries) ? data.libraries.filter((item): item is Library => item !== null && typeof item === 'object' && !Array.isArray(item) && typeof (item as Record<string, unknown>).id === 'string' && typeof (item as Record<string, unknown>).name === 'string' && typeof (item as Record<string, unknown>).rootPath === 'string' && typeof (item as Record<string, unknown>).enabled === 'boolean') : [];
        if (!active) return;
        if (!response.ok || envelope.ok !== true) throw new Error(i18nAttribute('读取书库失败'));
        setFolders(libraries);
        const root = await loadNode();
        if (active && root) {
          setSelectedPath(root.path);
          setExpanded(new Set([root.path]));
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : i18nAttribute('读取书库失败'));
      }
    }
    void load();
    return () => { active = false; };
  }, [i18nAttribute, loadNode]);

  const selectedLibrary = useMemo(() => folders
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

  async function continueSelectedLibrary() {
    if (!selectedLibrary) return;
    setContinuing(true);
    setError('');
    try {
      const next = await continueLibraryImport(selectedLibrary.id);
      setResult(next);
      if (next.requeuedFailed > 0 || next.enqueued) {
        toast.success(i18nAttribute('书库导入已继续'));
      } else {
        toast.success(i18nAttribute('没有新的导入任务'));
      }
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : i18nAttribute('继续导入失败');
      setError(message);
      toast.error(i18nAttribute('继续导入失败'), message);
    } finally {
      setContinuing(false);
    }
  }

  const rootNode = rootPath ? nodes[rootPath] : Object.values(nodes)[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 rounded-[20px] border border-[#DEDAD4] bg-[#FAF9F7] p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="font-semibold text-[#2A2825]"><I18nText>继续导入书库</I18nText></div>
          <p className="mt-1 text-sm leading-6 text-[#77716A]"><I18nText>选择已启用书库后继续扫描。导入任务和资源资产状态会在导入记录中更新。</I18nText></p>
        </div>
        <Button variant="secondary" icon={RefreshCw} loading={loadingPath === (selectedPath || '__root__')} loadingText={i18nAttribute('刷新中')} onClick={() => void loadNode(selectedPath || undefined)}><I18nText>刷新目录</I18nText></Button>
      </div>
      <div className="rounded-[16px] border border-[#F0DED5] bg-[#FFF8F4] px-4 py-3 text-sm leading-6 text-[#6D625B]">
        <div className="font-semibold text-[#3D3732]"><I18nText>有声书推荐目录</I18nText></div>
        <p className="mt-1"><I18nText>单卷使用“书名/音轨”，多卷使用“书名/卷名/音轨”；Disc、CD、Disk 目录只作为分轨层。目录名内嵌的作者可以识别，独立的“作者/书名”层级不会作为作者信息。</I18nText></p>
      </div>

      <div className="grid min-h-[420px] overflow-hidden rounded-[20px] border border-[#DEDAD4] bg-white md:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 border-b border-[#DEDAD4] p-3 md:border-b-0 md:border-r">
          <div className="mb-2 px-2 text-xs font-medium text-[#8A847D]"><I18nText>文件夹视图</I18nText></div>
          <div className="max-h-[520px] overflow-auto">
            {rootNode ? <DirectoryRow node={rootNode} level={0} nodes={nodes} expanded={expanded} selectedPath={selectedPath} loadingPath={loadingPath} onToggle={toggle} onSelect={setSelectedPath} /> : <div className="p-5 text-sm text-[#77716A]">{loadingPath ? i18nAttribute('正在读取目录…') : i18nAttribute('暂无可浏览目录')}</div>}
          </div>
        </div>
        <aside className="flex flex-col p-5">
          <div className="text-xs font-medium text-[#8A847D]"><I18nText>当前选择</I18nText></div>
          <div className="mt-2 break-all text-sm font-semibold leading-6 text-[#2A2825]">{selectedPath || i18nAttribute('尚未选择目录')}</div>
          <div className={cn('mt-4 rounded-xl px-3 py-2 text-xs leading-5', selectedLibrary ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800')}>
            {selectedLibrary ? i18nAttribute('使用“{value0}”继续导入', { value0: selectedLibrary.name }) : i18nAttribute('此目录不在已启用的书库内，不能继续导入。')}
          </div>
          {result ? (
            <div className="mt-4 space-y-2 border-t border-[#E9E5DF] pt-4 text-sm text-[#5F5953]">
              <div><I18nText>任务已提交：</I18nText><span data-i18n-skip>{result.taskId ?? '—'}</span></div>
              <div><I18nText>重新排队的失败任务：</I18nText>{result.requeuedFailed}</div>
              <div><I18nText>已加入队列：</I18nText>{result.enqueued ? i18nAttribute('是') : i18nAttribute('否')}</div>
            </div>
          ) : null}
          {error ? <div className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{error}</div> : null}
          <div className="mt-auto pt-4">
            <Button className="w-full" icon={Search} disabled={!selectedLibrary} loading={continuing} loadingText={i18nAttribute('继续中')} onClick={() => void continueSelectedLibrary()}><I18nText>继续导入书库</I18nText></Button>
          </div>
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
        <button type="button" onClick={() => void onToggle(node.path)} className="flex h-8 w-8 shrink-0 items-center justify-center" aria-label={isExpanded ? i18nExpression('收起 {value0}', { value0: node.name }) : i18nExpression('展开 {value0}', { value0: node.name })}>
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
